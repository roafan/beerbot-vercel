from flask import Flask, request, jsonify
import math
import json

app = Flask(__name__)

# ============================================================
# Utility
# ============================================================

def int_safe(x):
    try:
        return max(0, int(x))
    except:
        return 0


# ============================================================
# Rank #1 Forecast Model
# Ultra-slow exponential smoothing (alpha = 0.03)
# ============================================================

def forecast_smooth(weeks, role, alpha=0.03):
    if not weeks:
        return 0

    # Start with first week's incoming order
    f = int_safe(weeks[0]["roles"][role]["incoming_orders"])

    for w in weeks:
        incoming = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * incoming + (1 - alpha) * f

    return int(round(f))


# ============================================================
# Rank #1 Ordering Logic
# ============================================================

def compute_order_rank1(role_state, forecast, last_order, lead_time=4.6):

    inv = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # No safety stock for rank 1
    safety = 0

    # Real target inventory level
    target_inventory = forecast * (lead_time + 1)

    # Slow backlog correction: 7% — essential for top ranking
    backlog_adj = 0.07 * backlog

    # Raw desired order
    desired = target_inventory + backlog_adj - (inv + arriving)
    desired = max(0, int(round(desired)))

    # Heavy dampening: 12% reaction, 88% memory
    smoothed = 0.12 * desired + 0.88 * last_order

    return max(0, int(round(smoothed)))


# ============================================================
# Main BeerBot Handler
# ============================================================

def beerbot_handler(body):

    # Handshake
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_Optimized",
            "version": "v4.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "Rank #1 optimized BeerBot ready."
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # First week: low, stable start
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]

    # Compute ultra-stable forecasts
    forecasts = {r: forecast_smooth(weeks, r) for r in roles}
    orders = {}

    # -------------------------------------------------------------
    # BLACKBOX - Core leaderboard mode
    # -------------------------------------------------------------
    if mode == "blackbox":
        for r in roles:
            rs = last["roles"][r]
            last_order = int_safe(last.get("orders", {}).get(r, 4))
            orders[r] = compute_order_rank1(rs, forecasts[r], last_order)
        return {"orders": orders}

    # -------------------------------------------------------------
    # GLASSBOX MODE (optional)
    # -------------------------------------------------------------
    for r in roles:
        rs = last["roles"][r]
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        orders[r] = compute_order_rank1(rs, forecasts[r], last_order)

    # -------------------------------------------------------------
    # Factory override: small correction based on downstream demand
    # -------------------------------------------------------------
    downstream = forecasts["retailer"] + forecasts["wholesaler"] + forecasts["distributor"]

    fs = last["roles"]["factory"]
    invpos = int_safe(fs["inventory"]) + int_safe(fs["arriving_shipments"])

    desired_factory = max(0, downstream * 4.6 - invpos)
    last_factory_order = int_safe(last.get("orders", {}).get("factory", 4))

    # heavy smoothing again
    orders["factory"] = int(round(
        0.12 * desired_factory + 0.88 * last_factory_order
    ))

    return {"orders": orders}


# ============================================================
# Vercel HTTP Endpoint
# ============================================================

@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    result = beerbot_handler(body)
    return jsonify(result)
