"""
One-off historical backtest using REAL Deriv EUR/USD price data.

This is separate from the live bot - run it directly (e.g. via Railway's
Console tab, or locally) when you want to check how the strategy would
have performed over a real historical period. It's not part of the
bot's normal 24/7 operation.

USAGE:
    python historical_backtest.py [years_back] [target_rr]

    years_back defaults to 1.0 if not given.
    target_rr defaults to config.py's target_rr (5.0) if not given -
    several source videos described the trader personally using a fixed
    10R target instead, so this is worth testing separately, e.g.:
        python historical_backtest.py        -> 1 year, default 5R
        python historical_backtest.py 0.5    -> 6 months, default 5R
        python historical_backtest.py 1 10   -> 1 year, 10R target

    Note: target_rr only changes where the take-profit is placed, not
    which setups qualify as valid trades in the first place (that's
    governed by the stop-size/location/session filters, unaffected by
    this). So the same underlying trades get re-scored against a wider
    or narrower target - expect win rate to drop as target_rr increases
    (harder to run further before pulling back), with each win paying
    out proportionally more.

WHAT TO EXPECT:
    Fetching a full year of 1-minute data means dozens of paginated API
    requests to Deriv - this can take several minutes. If you're running
    it in Railway's Console, that's fine, just be patient and don't
    close the tab.

I have not run this against Deriv's live servers myself (no network
access in my environment) - the pagination and backtest logic are both
verified offline with mocked/synthetic data (test_deriv_connector.py,
run_example.py). This is the first real run against actual historical
data, and you're the one confirming the results make sense.
"""
import sys
import pandas as pd
from config import StrategyConfig
from signals import generate_signals
from backtest import run_backtest, summarize_trades, print_trade_list
from deriv_connector import DerivConnector

SYMBOL = "EURUSD"


def main():
    years_back = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

    cfg = StrategyConfig()
    if len(sys.argv) > 2:
        cfg.target_rr = float(sys.argv[2])
    conn = DerivConnector()

    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=int(years_back * 365))

    print(f"Fetching ~{years_back} year(s) of {SYMBOL} 1-min data from Deriv...")
    print(f"Target R:R for this run: {cfg.target_rr}")
    print(f"Range: {start} to {end}")
    print("This can take several minutes and many API requests - please be patient.\n")

    df = conn.get_historical_bars(SYMBOL, cfg.ltf_timeframe, start, end)
    print(f"\nFetched {len(df)} bars, from {df.index.min()} to {df.index.max()}")

    if df.empty:
        print("No data returned - aborting. Check symbol/timeframe or Deriv's "
              "available history for this instrument.")
        return

    print("\nRunning signal generation...")
    df_signals = generate_signals(df, cfg)

    print("Running backtest...")
    trades = run_backtest(df_signals, cfg)

    print("\n--- Backtest Results (real Deriv EUR/USD data) ---")
    summary = summarize_trades(trades, cfg)
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\n--- Itemized trade list ---")
    print_trade_list(trades)

    if trades:
        rows = []
        for t in trades:
            rows.append({
                "entry_time": t.entry_time, "direction": t.direction,
                "entry_price": t.entry_price, "exit_time": t.exit_time,
                "exit_price": t.exit_price, "reason": t.exit_reason,
                "r_multiple": round(t.r_multiple, 3),
            })
        out_df = pd.DataFrame(rows)
        out_df.to_csv("historical_backtest_trades.csv", index=False)
        print(f"\nFull trade log ({len(trades)} trades) saved to "
              f"historical_backtest_trades.csv")
    else:
        print("\nNo trades were triggered in this period - the filters "
              "may be too strict for this data, or genuinely no valid "
              "setups occurred. See STRATEGY_SPEC.md for the discretionary "
              "thresholds that are most worth tuning.")


if __name__ == "__main__":
    main()
