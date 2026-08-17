"""
Small mobile-friendly web dashboard. Runs in a background thread inside
the bot process, reads the bot's live in-memory state (via a shared dict)
plus the paper_trades.csv log, and serves a simple auto-refreshing page.

Open http://<host-ip>:5006 from your phone's browser (same network, or
via whatever public URL your cloud host gives you).
"""
from flask import Flask, render_template_string
import threading
import csv
import os

app = Flask(__name__)

# Shared state dict the bot updates each loop iteration.
# Keys: status, symbol, position (dict or None), equity, last_update,
#       tv_alerts_received (int)
shared_state = {
    "status": "starting",
    "symbol": "",
    "position": None,
    "equity": 0.0,
    "last_update": "",
    "tv_alerts_received": 0,
}

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="10">
    <title>PSO-RIMC Bot</title>
    <style>
        body { font-family: -apple-system, sans-serif; margin: 0; padding: 16px;
               background: #111; color: #eee; }
        h1 { font-size: 20px; margin-bottom: 4px; }
        .status { color: #4ade80; font-size: 14px; margin-bottom: 16px; }
        .card { background: #1c1c1c; border-radius: 12px; padding: 14px;
                margin-bottom: 12px; }
        .label { color: #888; font-size: 12px; text-transform: uppercase; }
        .value { font-size: 22px; margin-top: 2px; }
        .pos-long { color: #4ade80; }
        .pos-short { color: #f87171; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 6px 4px; border-bottom: 1px solid #2a2a2a; }
        th { color: #888; font-weight: normal; }
    </style>
</head>
<body>
    <h1>PSO+RIMC Bot</h1>
    <div class="status">{{ status }} &middot; last update {{ last_update }}</div>

    <div class="card">
        <div class="label">Equity</div>
        <div class="value">${{ "%.2f"|format(equity) }}</div>
    </div>

    <div class="card">
        <div class="label">Open position</div>
        {% if position %}
        <div class="value {{ 'pos-long' if position.direction == 1 else 'pos-short' }}">
            {{ 'LONG' if position.direction == 1 else 'SHORT' }} @ {{ position.entry_price }}
        </div>
        <div class="label" style="margin-top:8px">Stop / Target</div>
        <div>{{ position.stop_price }} / {{ position.target_price }}</div>
        {% else %}
        <div class="value">None</div>
        {% endif %}
    </div>

    <div class="card">
        <div class="label">TradingView alerts received (cross-check)</div>
        <div class="value">{{ tv_alerts_received }}</div>
    </div>

    <div class="card">
        <div class="label">Recent trades</div>
        <table>
            <tr><th>Time</th><th>Dir</th><th>Reason</th><th>PnL</th></tr>
            {% for t in recent_trades %}
            <tr>
                <td>{{ t.entry_time }}</td>
                <td>{{ 'L' if t.direction == '1' else 'S' }}</td>
                <td>{{ t.exit_reason }}</td>
                <td>{{ t.pnl }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""


def read_recent_trades(log_path: str, n: int = 10):
    if not os.path.exists(log_path):
        return []
    with open(log_path, "r") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows[-n:]))


@app.route("/")
def dashboard():
    state = shared_state
    log_path = state.get("log_path", "paper_trades.csv")
    trades = read_recent_trades(log_path)
    return render_template_string(
        PAGE_TEMPLATE,
        status=state["status"],
        last_update=state["last_update"],
        equity=state["equity"],
        position=state["position"],
        tv_alerts_received=state["tv_alerts_received"],
        recent_trades=trades,
    )


def run_dashboard(port: int = 5006):
    """Run the dashboard Flask app in a background thread."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return thread
