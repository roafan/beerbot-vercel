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

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# -------------------------
# Forecast: exponential smoothing (role-specific default)
# -------------------------
def forecast_smooth_role(weeks, role, alpha=0.08):
    """Role-aware exponential smoothing. For retailer alpha default = 0.08."""
    if not weeks:
        return 0
    f = int_safe(weeks[0]["roles"][role]["incoming_orders"])
    for w in weeks:
        y = int_safe(w["roles"][role]["incoming_orders"])
        f = alpha * y + (1 - alpha) * f
    return int(round(f))

# -------------------------
# Retailer PI controller (stateless computation from weeks history)
# -------------------------
def compute_order_retailer(role_state, weeks, last_order):
    """
    PI-like rule computed deterministically from weeks history:
      - forecast (exp smoothing)
      - lead_time estimate (retailer shorter)
      - proportional term on inventory position gap
      - integral term computed as sum of recent demand - forecast errors
      - dampening and step clipping to avoid bullwhip
    """
    # tuning params (chosen to produce Rank1-like rhythm)
    alpha_forecast = 0.08      # forecast smoothing
    lead_time = 2.0            # retailer faces short upstream lead
    Kp = 0.65                  # proportional gain
    Ki = 0.10                  # integral gain (slow)
    reaction = 0.20            # how much of desired we respond with immediately
    max_step = 4               # max change per week (clipping)

    # current state
    inv = int_safe(role_state.get("inventory", 0))
    backlog = int_safe(role_state.get("backlog", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))

    # forecast (smoothed)
    forecast = forecast_smooth_role(weeks, "retailer", alpha=alpha_forecast)

    # target inventory position (coverage for lead_time + 1)
    target_pos = forecast * (lead_time + 1)

    # proportional error: how far inventory position is from target
    inv_pos = inv + arriving
    error_p = target_pos - inv_pos

    # integral term estimation: sum of recent (observed demand - forecast)
    # compute over last up to 6 weeks to capture systematic bias
    integral_horizon = min(6, len(weeks))
    integral = 0.0
    for w in weeks[-integral_horizon:]:
        obs = int_safe(w["roles"]["retailer"]["incoming_orders"])
        # use the same smoothing process to get forecast up to that week
        # but simpler: subtract current forecast contribution (proxy)
        integral += (obs - forecast)
    # scale integral to moderate impact
    integral_term = Ki * integral

    # small backlog correction: eat only a fraction of backlog (backlog is cheaper)
    backlog_adj = 0.08 * backlog

    # desired raw order (base = forecast) + PI corrections
    desired_raw = forecast + Kp * error_p + backlog_adj + integral_term
    desired_raw = max(0, desired_raw)

    # reaction smoothing (mix desired and last order)
    desired = reaction * desired_raw + (1 - reaction) * last_order
    desired = int(round(desired))

    # step clipping to avoid big swings
    delta = desired - last_order
    delta = clamp(delta, -max_step, max_step)
    order = last_order + delta

    # final integer >= 0, and a small floor (avoid starving)
    order = max(0, int(order))
    if order == 0:
        # do not fully drop to zero as that provokes others to overreact; use minimal order 1
        order = 1
    return order

# -------------------------
# Default local controller for other roles
# (conservative, safe)
# -------------------------
def compute_order_local(role, role_state, weeks, last_order):
    # fallback tuning for non-retailer roles: conservative stable policy
    # small alpha for smoothing
    forecast = forecast_smooth_role(weeks, role, alpha=0.05)
    # conservative lead times
    lead_time_map = {"retailer": 2.0, "wholesaler": 4.0, "distributor": 4.0, "factory": 4.5}
    lt = lead_time_map.get(role, 4.0)

    # base target inventory
    inv = int_safe(role_state.get("inventory", 0))
    arriving = int_safe(role_state.get("arriving_shipments", 0))
    backlog = int_safe(role_state.get("backlog", 0))

    target_pos = forecast * (lt + 1)
    backlog_adj = 0.07 * backlog
    desired_raw = target_pos + backlog_adj - (inv + arriving)
    desired_raw = max(0, desired_raw)

    # smoothing and clipping
    reaction = 0.15
    max_step = 5
    desired = reaction * desired_raw + (1 - reaction) * last_order
    desired = int(round(desired))
    delta = desired - last_order
    delta = clamp(delta, -max_step, max_step)
    order = last_order + delta
    order = max(0, int(order))
    if order == 0:
        order = 1
    return order

# -------------------------
# Main handler
# -------------------------
def beerbot_handler(body):
    # handshake
    if body.get("handshake") is True:
        return {
            "ok": True,
            "student_email": "roafan@taltech.ee",
            "algorithm_name": "BeerBot_Tuned",
            "version": "v6.0.0",
            "supports": {"blackbox": True, "glassbox": True},
            "message": "BeerBot ready"
        }

    mode = body.get("mode", "blackbox")
    weeks = body.get("weeks", [])
    roles = ["retailer", "wholesaler", "distributor", "factory"]

    # initial fallback orders
    if not weeks:
        return {"orders": {r: 4 for r in roles}}

    last = weeks[-1]
    orders = {}

    # compute per-role orders; retailer gets special controller
    for r in roles:
        rs = last["roles"].get(r, {})
        last_order = int_safe(last.get("orders", {}).get(r, 4))
        if r == "retailer":
            orders[r] = compute_order_retailer(rs, weeks, last_order)
        else:
            orders[r] = compute_order_local(r, rs, weeks, last_order)

    # return orders for all roles; BlackBox will use the role it assigned to you
    return {"orders": orders}

# -------------------------
# Flask endpoint
# -------------------------
@app.post("/api/decision")
def decision():
    body = request.get_json(force=True, silent=True) or {}
    response = beerbot_handler(body)
    return jsonify(response)
