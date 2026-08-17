"""
Combined single-port web app: mobile dashboard + TradingView webhook
receiver, in ONE Flask app on ONE port.

Why this exists: tablet-friendly hosting platforms (Render, Railway,
Fly.io free tiers) expose only ONE public port per deployed service,
bound via the $PORT environment variable they set for you - unlike a
VPS, you can't just open two arbitrary ports (5005 and 5006) and expect
both to be reachable from outside. This merges dashboard.py and
tradingview_webhook.py's routes into one app so a single-port deployment
works correctly.

Routes:
    GET  /         -> mobile dashboard
    POST /webhook  -> TradingView alert receiver
"""
import os
import threading
import queue
from flask import Flask, request, jsonify, render_template_string
from dashboard import PAGE_TEMPLATE, shared_state, read_recent_trades

app = Flask(__name__)
alert_queue: "queue.Queue" = queue.Queue()


@app.route("/")
def index():
    state = shared_state
    log_path = state.get("log_path", "paper_trades.csv")
    trades = read_recent_trades(log_path)
    return render_template_string(
        PAGE_TEMPLATE,
        status=state["status"], last_update=state["last_update"],
        equity=state["equity"], position=state["position"],
        tv_alerts_received=state["tv_alerts_received"],
        recent_trades=trades,
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    alert_queue.put(data)
    print(f"[TradingView webhook] received: {data}")
    return jsonify({"status": "ok"})


def get_latest_alert(timeout: float = 0.1):
    try:
        return alert_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def run_web_app():
    """Binds to the platform-assigned port (Render/Railway/Fly.io set
    $PORT for you) so a single-port deployment works. Falls back to 5006
    for local testing where $PORT isn't set."""
    port = int(os.environ.get("PORT", 5006))
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return thread
