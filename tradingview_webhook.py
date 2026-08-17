"""
Optional: a small local webhook server that receives alerts from a
TradingView Pine Script strategy/indicator (via TradingView's built-in
webhook alert feature) and drops them into a shared queue the bot can
check.

This does NOT pull live data from TradingView (no such API exists for
retail accounts) -- it only *receives* alerts TradingView sends out when
a Pine condition you define fires. Useful as a manual cross-check/second
opinion against the MT5-driven signals, not as a primary data source.

Setup on TradingView's side:
    1. Build a Pine Script indicator/strategy with an alertcondition().
    2. Create an alert on it, webhook URL = http://<this-machine-ip>:5005/webhook
       (needs to be reachable from TradingView's servers -- for a home
       machine you'll need port forwarding or a tunnel like ngrok).
    3. Message body: any JSON, e.g. {"symbol": "EURUSD", "direction": "sell"}

Requires: pip install flask
"""
from flask import Flask, request, jsonify
import queue
import threading

app = Flask(__name__)
alert_queue: "queue.Queue" = queue.Queue()


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    alert_queue.put(data)
    print(f"[TradingView webhook] received: {data}")
    return jsonify({"status": "ok"})


def run_server(port: int = 5005):
    """Run the Flask server in a background thread."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return thread


def get_latest_alert(timeout: float = 0.1):
    """Non-blocking-ish check for a new alert. Returns None if none waiting."""
    try:
        return alert_queue.get(timeout=timeout)
    except queue.Empty:
        return None
