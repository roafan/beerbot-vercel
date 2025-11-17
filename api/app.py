from flask import Flask, request, jsonify
import math
import json

app = Flask(__name__)

# ============================================================
# Helper utilities
# ============================================================

def int_safe(x):
    try:
        return max(0, int(x))
    except:
        return 0

# ============================================================
# Forecast: ultra-stable exponential smoothing
# (α = 0.05 is tuned for top-3 performance)
# ============================================================

def forecast_smooth(weeks, role, alpha=0.05):
    if not weeks:
        return 0

    # Initialize forecast with first observed incoming order
    f = int_safe(weeks[0]["roles"][role]["incoming_orders"])

    for w in weeks:
        y = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * y + (1 - alpha) * f

    return int(round(f))

# ============================================================
# Top-3 optimized ordering logic
# ============================================================

def compute_order(role_state, forecast, last_order, lead_time=4):
    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # No safety stock – essential for top placement
    safety = 0

    # Expected inventory required for LT
    target_inventory = forecast * (lead_time + 1)

    # Very gentle backlog correction (10%)
    backlog_adjust = 0.1 * backlog

    desired = target_inventory + backlog_adjust - (inventory + arriving)
    desired = max(0, int(round(desired)))

    # Strong dampening to kill bullwhip (15% reaction)
    smoothed = 0.15 * desired + 0.85 * last_order

    return max(0, int(round(smoothed)))

# ============================================================
# Main BeerBot handler
# ============================================================

def beerbot_handler(body):

    # ------------------------------------
    # Handshake
    # ------------------------------------
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_Top3_Optimized",
            "version": "v3.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "Top-3 optimized BeerBot ready."
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # First week: stable start
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]

    # Stable smoothed forecasts
    forecasts = {r: forecast_smooth(weeks, r) for r in roles}

    orders = {}

    # ---------------------------------------------------------
    # BLACKBOX MODE (Leaderboard mode)
    # ---------------------------------------------------------
    if mode == "blackbox":
        for r in roles:
            rs = last["roles"][r]
            last_order = int_safe(last.get("orders", {}).get(r, 4))
            orders[r] = compute_order(rs, forecasts[r], last_order)
        return {"orders": orders}

    # ---------------------------------------------------------
    # GLASSBOX MODE (Optional)
    # ---------------------------------------------------------
    for r in roles:
        rs = last["roles"][r]
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        orders[r] = compute_order(rs, forecasts[r], last_order)

    # Factory slight stabilization logic
    down_demand = (
        forecasts["retailer"] +
        forecasts["wholesaler"] +
        forecasts["distributor"]
    )

    fs = last["roles"]["factory"]
    inv_pos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])

    factory_desired = max(0, down_demand * 4 - inv_pos)
    last_factory = int_safe(last.get("orders", {}).get("factory", 4))

    orders["factory"] = int(round(0.15 * factory_desired + 0.85 * last_factory))

    return {"orders": orders}

# ============================================================
# Vercel endpoint
# ============================================================

@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    response = beerbot_handler(body)
    return jsonify(response)

