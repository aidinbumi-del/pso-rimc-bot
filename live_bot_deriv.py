"""
Main live bot (Deriv + TradingView cross-check + mobile dashboard).

Same architecture as live_bot_oanda.py, with Deriv's WebSocket API
swapped in for OANDA's REST API - use this version if OANDA isn't
available in your country (e.g. Zimbabwe).

SETUP:
    1. pip install -r requirements.txt
    2. (Optional) Add the Pine Script to a TradingView chart, create an
       alert with webhook URL http://<this-host>:5005/webhook
    3. Run: python live_bot_deriv.py
    4. Open http://<this-host>:5006 on your phone.

No Deriv account/token is required for this - price data used here is
public. See deriv_connector.py for what changes once you want real order
placement later (a different model than OANDA/MT5's simple market orders).

I cannot run this against a real Deriv connection myself - no network
access in this sandbox. deriv_connector.py's parsing logic is verified
with mocked response tests (test_deriv_connector.py); the actual live
WebSocket connection is yours to confirm on first run.
"""
import time
from datetime import datetime

from config import StrategyConfig
from signals import generate_signals
from structure import find_prior_swing_extreme
from paper_broker import PaperAccount
from deriv_connector import DerivConnector
import web_app


# ---------------- CONFIG ----------------
SYMBOL = "EURUSD"  # plain format - mapped internally to Deriv's frxEURUSD
POLL_SECONDS = 15
BARS_TO_FETCH = 1000
STARTING_EQUITY = 10000.0
LOG_PATH = "paper_trades.csv"
# -----------------------------------------


def check_tv_confirmation(direction: int, window_minutes: int) -> bool:
    confirmed = False
    while True:
        alert = web_app.get_latest_alert(timeout=0.05)
        if alert is None:
            break
        web_app.shared_state["tv_alerts_received"] += 1
        alert_dir = 1 if str(alert.get("direction", "")).lower() == "buy" else -1
        if alert_dir == direction:
            confirmed = True
    return confirmed


def main():
    cfg = StrategyConfig()
    # Deriv's public tick feed has no true bid/ask spread, so the spread
    # filter isn't meaningful with this data source - disable it here
    # rather than silently mis-applying it.
    cfg.max_spread_pips = float("inf")

    account = PaperAccount(cfg, starting_equity=STARTING_EQUITY, log_path=LOG_PATH)
    conn = DerivConnector()

    web_app.shared_state["log_path"] = LOG_PATH
    web_app.shared_state["symbol"] = SYMBOL
    web_app.shared_state["equity"] = account.equity
    web_app.shared_state["status"] = "running"

    print("Starting web app (dashboard on / + webhook on /webhook) ...")
    web_app.run_web_app()

    print(f"Connected to Deriv (public data). Trading {SYMBOL}. Ctrl+C to stop.\n")

    last_bar_time = None

    try:
        while True:
            df = conn.get_recent_bars(SYMBOL, cfg.ltf_timeframe, BARS_TO_FETCH)
            if df.empty:
                time.sleep(POLL_SECONDS)
                continue

            latest_bar_time = df.index[-1]
            latest_bar = df.iloc[-1]

            if account.position is not None:
                i = len(df) - 1
                prior_extreme = find_prior_swing_extreme(
                    df, i, account.position.direction
                )
                if prior_extreme is not None:
                    account.update_breakeven(
                        prior_extreme, latest_bar["high"], latest_bar["low"]
                    )
                account.check_exit(
                    latest_bar_time, latest_bar["high"], latest_bar["low"]
                )

            if latest_bar_time != last_bar_time:
                last_bar_time = latest_bar_time
                df_signals = generate_signals(df, cfg)
                last_row = df_signals.iloc[-1]
                day_key = latest_bar_time.date()

                if last_row["setup_valid"] and account.can_open_new_trade(day_key):
                    direction = int(last_row["direction"])

                    tv_ok = True
                    if cfg.require_tv_confirmation:
                        tv_ok = check_tv_confirmation(
                            direction, cfg.tv_confirmation_window_minutes
                        )
                        if not tv_ok:
                            print("[SKIP] Deriv setup found but no "
                                  "TradingView confirmation yet.")
                    else:
                        check_tv_confirmation(direction, cfg.tv_confirmation_window_minutes)

                    if tv_ok:
                        account.open_position(
                            direction=direction,
                            entry_time=latest_bar_time,
                            entry_price=float(last_row["entry_price"]),
                            stop_price=float(last_row["stop_price"]),
                            target_price=float(last_row["target_price"]),
                        )

            web_app.shared_state["equity"] = account.equity
            web_app.shared_state["last_update"] = datetime.now().strftime("%H:%M:%S")
            if account.position:
                p = account.position
                web_app.shared_state["position"] = {
                    "direction": p.direction, "entry_price": round(p.entry_price, 5),
                    "stop_price": round(p.stop_price, 5),
                    "target_price": round(p.target_price, 5),
                }
            else:
                web_app.shared_state["position"] = None

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping bot...")
        web_app.shared_state["status"] = "stopped"
        print("\n--- Session summary ---")
        for k, v in account.summary().items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
