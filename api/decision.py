# api/decision.py
from http.server import BaseHTTPRequestHandler
import json
import math

# ================================
# Helper utilities
# ================================
def int_safe(x):
    try:
        return max(0, int(x))
    except:
        return 0

# ================================
# Forecast: exponential smoothing
# ================================
def forecast_smooth(weeks, role, alpha=0.2):
    """Exponential smoothing of incoming orders (less reactive than moving avg)."""
    if not weeks:
        return 0

    # Initialize with first observed incoming order
    first = int_safe(weeks[0]["roles"][role]["incoming_orders"])
    f = first

    for w in weeks:
        y = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * y + (1 - alpha) * f

    return int(round(f))


# ================================
# Base ordering logic (soft correction)
# ================================
def compute_order(role_state, forecast, last_order, lead_time=5):
    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # No safety stock: keep it controlled
    safety = 0

    # Target inventory: forecast × (L+1)
    target = forecast * (lead_time + 1) + safety

    # Backlog correction factor (very slow)
    backlog_adjust = 0.3 * backlog  # instead of full backlog

    desired = target + backlog_adjust - (inventory + arriving)

    # Clip negative
    desired = max(0, int(round(desired)))

    # Order dampening (HUGE improvement): prevents oscillations
    smoothed = 0.3 * desired + 0.7 * last_order

    return max(0, int(round(smoothed)))


# ================================
# Main BeerBot Handler
# ================================
def beerbot_handler(body):
    # ----------------------------------
    # Handshake Response
    # ----------------------------------
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_Stable_PI",
            "version": "v2.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "BeerBot stable controller ready"
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # First week: default conservative start
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]
    forecasts = {r: forecast_smooth(weeks, r) for r in roles}

    orders = {}

    # ----------------------------------
    # Blackbox mode (your score depends on this one!)
    # ----------------------------------
    if mode == "blackbox":
        for r in roles:
            rs = last["roles"][r]
            last_order = int_safe(last.get("orders", {}).get(r, 4))
            orders[r] = compute_order(rs, forecasts[r], last_order)
        return {"orders": orders}

    # ----------------------------------
    # Glassbox (optional improvement)
    # ----------------------------------
    for r in roles:
        rs = last["roles"][r]
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        orders[r] = compute_order(rs, forecasts[r], last_order)

    # Factory special override (soft push)
    downstream_demand = (
        forecasts["retailer"] +
        forecasts["wholesaler"] +
        forecasts["distributor"]
    )

    fs = last["roles"]["factory"]
    invpos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])

    factory_target = downstream_demand * 5  # soft multiplier
    factory_order = 0.3 * max(0, factory_target - invpos) + 0.7 * int_safe(last.get("orders", {}).get("factory", 4))

    orders["factory"] = int(round(factory_order))
    return {"orders": orders}


# ================================
# HTTP Handler for Vercel
# ================================
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body_raw = self.rfile.read(length)
        body = json.loads(body_raw.decode("utf-8"))

        response = beerbot_handler(body)
        response_json = json.dumps(response)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response_json.encode("utf-8"))
