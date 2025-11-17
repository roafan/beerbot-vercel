from http.server import BaseHTTPRequestHandler
import json
import math

# ==========================================
# Helper: safe integer
# ==========================================
def int_safe(x):
    try: return max(0, int(x))
    except: return 0


# ==========================================
# Forecast: EXponential smoothing (very slow)
# ==========================================
def forecast_smooth(weeks, role, alpha=0.05):
    """Stable and slow-reacting forecast (best for bullwhip reduction)."""
    if not weeks:
        return 0

    # Initialize forecast with first week's observed demand
    f = int_safe(weeks[0]["roles"][role]["incoming_orders"])

    for w in weeks:
        y = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * y + (1 - alpha) * f

    return int(round(f))


# ==========================================
# Optimal Top-3 Ordering Policy
# ==========================================
def compute_order(role_state, forecast, last_order, lead_time=4):
    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # No safety stock in top-performing bots
    safety = 0

    # Base target inventory
    target_inventory = forecast * (lead_time + 1) + safety

    # Very slow backlog correction (10%)
    backlog_adjust = 0.1 * backlog

    # Desired raw order
    desired = target_inventory + backlog_adjust - (inventory + arriving)
    desired = max(0, int(round(desired)))

    # Strong dampening: 15% response, 85% memory
    smoothed = 0.15 * desired + 0.85 * last_order

    return max(0, int(round(smoothed)))


# ==========================================
# Main Handler
# ==========================================
def beerbot_handler(body):

    # Handshake
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_Top3_Optimized",
            "version": "v3.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "Top-3 optimized BeerBot active."
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # Week 1: start with low, stable orders
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]

    # Stable smoothed forecasts
    forecasts = {r: forecast_smooth(weeks, r) for r in roles}
    orders = {}

    # --------------------------
    # BLACKBOX (Leaderboard mode)
    # --------------------------
    if mode == "blackbox":
        for r in roles:
            rs = last["roles"][r]
            last_order = int_safe(last.get("orders", {}).get(r, 4))
            orders[r] = compute_order(rs, forecasts[r], last_order)
        return {"orders": orders}

    # --------------------------
    # GLASSBOX (Optional)
    # --------------------------
    for r in roles:
        rs = last["roles"][r]
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        orders[r] = compute_order(rs, forecasts[r], last_order)

    # Factory subtle boost
    down = forecasts["retailer"] + forecasts["wholesaler"] + forecasts["distributor"]
    fs = last["roles"]["factory"]
    inv_pos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])

    factory_desired = max(0, down * 4 - inv_pos)
    last_factory = int_safe(last.get("orders", {}).get("factory", 4))

    orders["factory"] = int(round(0.15 * factory_desired + 0.85 * last_factory))

    return {"orders": orders}


# ==========================================
# HTTP handler for Vercel
# ==========================================
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
