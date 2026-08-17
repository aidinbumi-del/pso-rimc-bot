"""
Example runner. By default generates synthetic 1-minute OHLC data just to
prove the pipeline runs end-to-end -- this is NOT real market data and the
results below mean nothing about real profitability.

To use with real data:
    1. Load your own 1-minute OHLC CSV into a DataFrame with columns
       open, high, low, close and a DatetimeIndex (ideally already in
       London time, or adjust session_start/end in config.py).
    2. Replace the `df = generate_synthetic_data(...)` line below with
       your own data loading, e.g.:
           df = pd.read_csv("your_data.csv", index_col="time", parse_dates=True)
    3. Re-run this script.

Good sources for real 1-min forex data: your broker's export tool (e.g.
MT4/MT5 history center), Dukascopy's historical data feed, or a paid data
vendor. I can't fetch live/historical forex tick data myself.
"""
import numpy as np
import pandas as pd
from config import StrategyConfig
from signals import generate_signals
from backtest import run_backtest, summarize_trades


def generate_synthetic_data(days: int = 30, seed: int = 42) -> pd.DataFrame:
    """Random-walk placeholder data, London-session-hours only, for
    pipeline testing. Not representative of real market structure.
    Volatility tuned so breakouts occasionally produce 2-5 pip ranges,
    matching the strategy's stop-size filter, purely so this demo
    actually exercises the full trade pipeline end-to-end."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2025-01-06 00:00")  # a Monday
    timestamps = pd.date_range(start, periods=days * 24 * 60, freq="1min")

    price = 1.1000
    rows = []
    for ts in timestamps:
        drift = rng.normal(0, 0.00010)
        if 8 <= ts.hour < 10:
            drift += rng.choice([-1, 1]) * 0.00020
        price += drift
        o = price
        h = price + abs(rng.normal(0, 0.00012))
        l = price - abs(rng.normal(0, 0.00012))
        c = price + rng.normal(0, 0.00010)
        price = c
        rows.append((ts, o, h, l, c))

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df = df.set_index("time")
    return df


def main():
    cfg = StrategyConfig()

    print("Generating synthetic placeholder data (NOT real market data)...")
    df = generate_synthetic_data(days=60)

    print("Running signal generation...")
    df_signals = generate_signals(df, cfg)

    print("Running backtest...")
    trades = run_backtest(df_signals, cfg)

    print("\n--- Results (synthetic data — for pipeline testing only) ---")
    summary = summarize_trades(trades, cfg)
    for k, v in summary.items():
        print(f"{k}: {v}")

    if trades:
        print("\nFirst 5 trades:")
        for t in trades[:5]:
            print(f"  {t.entry_time} {'LONG' if t.direction==1 else 'SHORT'} "
                  f"entry={t.entry_price:.5f} stop={t.initial_stop:.5f} "
                  f"target={t.target:.5f} exit={t.exit_price} "
                  f"reason={t.exit_reason} R={t.r_multiple:.2f}")


if __name__ == "__main__":
    main()
