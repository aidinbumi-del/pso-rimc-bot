"""
Main live bot. Polls MT5 for the latest bars on a schedule, runs the same
signal-generation logic used in the backtest, manages one paper position
at a time, and logs everything to paper_trades.csv.

USAGE:
    1. Install MetaTrader5 terminal + log into a DEMO account.
    2. pip install MetaTrader5 pandas numpy
    3. Edit the CONFIG section below (symbol, MT5 login details if needed).
    4. python live_bot.py

This is paper trading only -- it reads live MT5 prices but places no real
orders. See mt5_connector.place_market_order() for the (unused-by-default)
real-order function, which you should only wire in after you've validated
this extensively on demo/paper results over weeks, not days.

I cannot run or test this myself -- no network access and no MT5 terminal
in this sandbox. You are the one validating the live connection works.
"""
import time
from datetime import datetime, date

from config import StrategyConfig
from signals import generate_signals
from structure import find_prior_swing_extreme
from paper_broker import PaperAccount
import mt5_connector as mt5c


# ---------------- CONFIG ----------------
SYMBOL = "EURUSD"
POLL_SECONDS = 15          # how often to check for new bars / manage position
BARS_TO_FETCH = 1000       # rolling window fed into signal generation
STARTING_EQUITY = 10000.0
# -----------------------------------------


def main():
    cfg = StrategyConfig()
    account = PaperAccount(cfg, starting_equity=STARTING_EQUITY)

    print(f"Connecting to MT5...")
    mt5c.connect()  # add login=, password=, server= if not already logged in
    print("Connected. Starting live loop (Ctrl+C to stop).\n")

    last_bar_time = None

    try:
        while True:
            df = mt5c.get_recent_bars(SYMBOL, cfg.ltf_timeframe, BARS_TO_FETCH)

            latest_bar_time = df.index[-1]
            latest_bar = df.iloc[-1]

            # --- Manage any open paper position against the newest bar ---
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

            # --- Only look for new setups once per new closed bar ---
            if latest_bar_time != last_bar_time:
                last_bar_time = latest_bar_time
                df_signals = generate_signals(df, cfg)
                last_row = df_signals.iloc[-1]
                day_key = latest_bar_time.date()

                if last_row["setup_valid"] and account.can_open_new_trade(day_key):
                    bid, ask = mt5c.get_current_price(SYMBOL)
                    spread_pips = abs(ask - bid) / cfg.pip_size
                    if spread_pips > cfg.max_spread_pips:
                        print(f"[SKIP] Setup found but spread too wide: "
                              f"{spread_pips:.1f} pips > {cfg.max_spread_pips} max")
                    else:
                        account.open_position(
                            direction=int(last_row["direction"]),
                            entry_time=latest_bar_time,
                            entry_price=float(last_row["entry_price"]),
                            stop_price=float(last_row["stop_price"]),
                            target_price=float(last_row["target_price"]),
                        )

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping bot...")
        print("\n--- Session summary ---")
        for k, v in account.summary().items():
            print(f"{k}: {v}")
    finally:
        mt5c.disconnect()


if __name__ == "__main__":
    main()
