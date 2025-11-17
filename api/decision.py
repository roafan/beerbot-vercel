# api/decision.py

from flask import Flask, request, jsonify
import math
from typing import Dict, Any, List

app = Flask(__name__)

# -------------------------------------------------------------
# Utility
# -------------------------------------------------------------
def int_safe(x):
    try:
        xi = int(x)
    except Exception:
        xi = 0
    return max(0, xi)

# -------------------------------------------------------------
# Forecast: simple moving average over last <= 3 weeks
# -------------------------------------------------------------
def forecast_moving_average(weeks: List[Dict[str,Any]], role: str, window: int = 3) -> int:
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

# -------------------------------------------------------------
# Base-stock deterministic order rule
# -------------------------------------------------------------
def compute_order_for_role(role_state: Dict[str,int], demand_forecast: int, lead_time:int = 2) -> int:
    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving_shipments = int_safe(role_state.get("arriving_shipments", 0))

    safety = math.ceil(0.5 * math.sqrt(demand_forecast + 1))
    target_inventory = demand_forecast * (lead_time + 1) + safety

    order = target_inventory + backlog - (inventory + arriving_shipments)
    return max(0, int(order))

# -------------------------------------------------------------
# BeerBot handler (handshake + weekly decisions)
# -------------------------------------------------------------
def beerbot_handler(body: Dict[str,Any]) -> Dict[str,Any]:

    # Handshake
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "firstname.lastname@taltech.ee",
            "algorithm_name": "BeerBot_PI_Controller",
            "version": "v1.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "BeerBot ready"
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles_list = ["retailer", "wholesaler", "distributor", "factory"]

    # No weeks provided → return default orders
    if not isinstance(weeks, list) or len(weeks) == 0:
        return {
            "orders": {
                "retailer": 10,
                "wholesaler": 10,
                "distributor": 10,
                "factory": 10
            }
        }

    forecasts = {
        r: forecast_moving_average(weeks, r, window=3)
        for r in roles_list
    }

    lead_time_estimate = 2
    last = weeks[-1]
    orders = {}

    # Blackbox (independent)
    if mode == "blackbox":
        for r in roles_list:
            role_state = last["roles"].get(r, {})
            orders[r] = compute_order_for_role(role_state, forecasts[r], lead_time=lead_time_estimate)
        return {"orders": orders}

    # Glassbox (coordinated)
    else:
        for r in roles_list:
            role_state = last["roles"].get(r, {})
            orders[r] = compute_order_for_role(role_state, forecasts[r], lead_time=lead_time_estimate)

        downstream_sum = forecasts["retailer"] + forecasts["wholesaler"] + forecasts["distributor"]
        factory_state = last["roles"].get("factory", {})

        invpos = int_safe(factory_state.get("inventory", 0)) + int_safe(factory_state.get("arriving_shipments", 0))
        factory_target = downstream_sum * (lead_time_estimate + 1) + math.ceil(0.5 * math.sqrt(downstream_sum + 1))
        orders["factory"] = max(0, int(factory_target - invpos))

        return {"orders": orders}

# -------------------------------------------------------------
# Flask route (used by Vercel)
# -------------------------------------------------------------
@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(beerbot_handler(body))

# -------------------------------------------------------------
# Vercel entrypoint
# -------------------------------------------------------------
def handler(event, context):
    return app(event, context)
