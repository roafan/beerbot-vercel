from flask import Flask, request, jsonify
import math
from typing import Dict, Any, List

app = Flask(__name__)

# ------------------------------
# Your BeerBot implementation
# ------------------------------

def int_safe(x):
    try:
        xi = int(x)
    except Exception:
        xi = 0
    return max(0, xi)

def forecast_moving_average(weeks, role, window=3):
    if not weeks:
        return 0
    vals = []
    for w in weeks[-window:]:
        try:
            v = int_safe(w["roles"][role]["incoming_orders"])
        except Exception:
            v = 0
        vals.append(v)
    if not vals:
        return 0
    return int(round(sum(vals) / len(vals)))

def compute_order_for_role(role_state, demand_forecast, lead_time=2):
    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving_shipments = int_safe(role_state.get("arriving_shipments", 0))

    safety = math.ceil(0.5 * math.sqrt(demand_forecast + 1))
    target_inventory = demand_forecast * (lead_time + 1) + safety

    order = target_inventory + backlog - (inventory + arriving_shipments)
    return max(0, int(order))

def beerbot_handler(body):
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_PI_Controller",
            "version": "v1.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "BeerBot ready"
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    if not weeks:
        return {"orders": {r: 10 for r in roles}}

    forecasts = {r: forecast_moving_average(weeks, r) for r in roles}
    lead_time = 2
    last = weeks[-1]

    orders = {}

    if mode == "blackbox":
        for r in roles:
            rs = last["roles"].get(r, {})
            orders[r] = compute_order_for_role(rs, forecasts[r], lead_time)
        return {"orders": orders}

    # Glassbox
    for r in roles:
        rs = last["roles"].get(r, {})
        orders[r] = compute_order_for_role(rs, forecasts[r], lead_time)

    downstream = forecasts["retailer"] + forecasts["wholesaler"] + forecasts["distributor"]
    fs = last["roles"]["factory"]
    invpos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])
    target = downstream * (lead_time + 1) + math.ceil(0.5 * math.sqrt(downstream + 1))
    orders["factory"] = max(0, target - invpos)

    return {"orders": orders}


# ------------------------------
# Flask route for Vercel
# ------------------------------
@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    response = beerbot_handler(body)
    return jsonify(response)
