from flask import Flask, request, jsonify
import math

app = Flask(__name__)

# -------------------------
# Utilities
# -------------------------
def int_safe(x):
    try:
        return max(0, int(x))
    except:
        return 0

def clamp(x, a, b):
    return max(a, min(b, x))

# -------------------------
# Forecast: ultra-slow exponential smoothing
# -------------------------
def forecast_smooth(weeks, role, alpha=0.03):
    """Very stable forecast using exponential smoothing (deterministic)."""
    if not weeks:
        return 0
    # initialize with first observed incoming_orders
    f = int_safe(weeks[0]["roles"][role]["incoming_orders"])
    for w in weeks:
        y = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * y + (1 - alpha) * f
    return int(round(f))

# -------------------------
# Estimate lead time (conservative)
# -------------------------
def estimate_lead_time(weeks, role):
    """
    Conservative heuristic for lead time:
    - default 4.0 weeks (works well for standard MIT game)
    - minor role-specific adjustments (retailer shorter)
    Deterministic and simple.
    """
    base = 4.0
    if role == "retailer":
        return 2.0  # retailer typically faces shortest upstream lead time
    return base

# -------------------------
# Local (role-only) order computation
# -------------------------
def compute_local_order(role_state, forecast, last_order,
                        lead_time=4.0,
                        backlog_coef=0.07,
                        reaction=0.12,
                        max_step=5):
    """
    role_state: dict with inventory, backlog, arriving_shipments
    forecast: int (smoothed demand)
    last_order: int (previous order for this role)
    Returns integer order >= 0
    """

    inventory = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # No explicit safety stock (top-performing policy)
    safety = 0

    # Target inventory (coverage for lead_time + 1)
    target_inventory = forecast * (lead_time + 1) + safety

    # Small backlog correction (allow some backlog to reduce inventory cost)
    backlog_adjust = backlog_coef * backlog

    # Raw desired order to move inventory position toward target + small backlog correction
    desired = target_inventory + backlog_adjust - (inventory + arriving)
    desired = max(0, int(round(desired)))

    # Dampening: mostly remember last order (very stable)
    smoothed = reaction * desired + (1 - reaction) * last_order
    smoothed = int(round(smoothed))

    # Prevent extreme week-to-week changes: clip change to +/- max_step
    delta = smoothed - last_order
    delta = clamp(delta, -max_step, max_step)
    order = last_order + delta

    # Final safety: integer >= 0
    return max(0, int(order))

# -------------------------
# Main BeerBot handler
# -------------------------
def beerbot_handler(body):
    # handshake
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_BlackBox_Robust",
            "version": "v5.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "BeerBot ready"
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # default conservative starter orders when no history
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]
    orders = {}

    # compute forecasts per role
    forecasts = {r: forecast_smooth(weeks, r) for r in roles}

    # compute local role orders independently (safe for BlackBox)
    for r in roles:
        role_state = last["roles"].get(r, {})
        # determine last order safely
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        # estimate lead time conservatively
        lt = estimate_lead_time(weeks, r)
        # compute order with conservative tuning
        orders[r] = compute_local_order(
            role_state=role_state,
            forecast=forecasts[r],
            last_order=last_order,
            lead_time=lt,
            backlog_coef=0.07,   # 7% backlog correction
            reaction=0.12,       # 12% response to desired
            max_step=5           # at most +/-5 units change/week
        )

    # For GlassBox mode, keep same local logic (no cross-role aggressive coordination)
    # Return deterministic orders for all roles — simulator will use the relevant one in BlackBox.
    return {"orders": orders}

# -------------------------
# Flask endpoint for Vercel
# -------------------------
@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    response = beerbot_handler(body)
    return jsonify(response)
