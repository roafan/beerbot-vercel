# api/decision.py
from http.server import BaseHTTPRequestHandler
import json
import math
from typing import Dict, Any, List

# ------------------------- #
# Your BeerBot code below
# ------------------------- #

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
            "student_email": "firstname.lastname@taltech.ee",
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

    for r in roles:
        rs = last["roles"].get(r, {})
        orders[r] = compute_order_for_role(rs, forecasts[r], lead_time)

    downstream = forecasts["retailer"] + forecasts["wholesaler"] + forecasts["distributor"]
    fs = last["roles"]["factory"]
    invpos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])
    target = downstream * (lead_time + 1) + math.ceil(0.5 * math.sqrt(downstream + 1))
    orders["factory"] = max(0, target - invpos)
    return {"orders": orders}

# -------------------------------- #
# Vercel handler using BaseHTTPRequestHandler
# -------------------------------- #
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_len = int(self.headers.get("content-length", 0))
        body_raw = self.rfile.read(content_len)
        body = json.loads(body_raw.decode("utf-8"))

        response = beerbot_handler(body)
        response_json = json.dumps(response)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        self.wfile.write(response_json.encode("utf-8"))
