"""
Historical backtest across EUR/USD AND XAU/USD (gold) combined, run
independently per instrument then aggregated.

IMPORTANT CAVEAT: the strategy's source material (the YouTube transcripts
this whole system was built from) only ever discussed EUR/USD. The pip-
based thresholds (2.2-5 pip stops, 0.0001 pip size) are specific to that.
Gold moves in dollars with very different scale and volatility, so this
script uses a SEPARATE config for gold with my own best-guess starting
values (see GOLD_MIN_STOP / GOLD_MAX_STOP below) - these are NOT derived
from the source material like the EUR/USD numbers are. Treat gold results
here as a rough first look, not a validated setup - you'll likely want to
tune these against real gold charts before trusting them.

R-multiples ARE meaningfully comparable across instruments (that's the
point of R-normalization - a 5R gold trade and a 5R EUR/USD trade both
risked the same proportion of account equity), so the combined summary
stats are legitimate even though the two instruments trade very
differently in raw price terms.

USAGE:
    python combined_backtest.py [years_back]
    (defaults to 0.5 years if not given)
"""
import sys
import copy
import pandas as pd
from config import StrategyConfig
from signals import generate_signals
from backtest import run_backtest, summarize_trades
from deriv_connector import DerivConnector

# --- Gold-specific overrides - my own guesses, not from source material ---
GOLD_PIP_SIZE = 0.01      # common convention: 1 "pip" = $0.01 for XAUUSD
GOLD_MIN_STOP = 5.0       # = $0.05 - unverified guess, tune against real data
GOLD_MAX_STOP = 200.0     # = $2.00 - unverified guess, tune against real data


def make_gold_config(base: StrategyConfig) -> StrategyConfig:
    cfg = copy.deepcopy(base)
    cfg.pip_size = GOLD_PIP_SIZE
    cfg.min_stop_pips = GOLD_MIN_STOP
    cfg.max_stop_pips = GOLD_MAX_STOP
    return cfg


def run_instrument(conn, symbol, cfg, start, end):
    print(f"\n=== {symbol} ===")
    print(f"Fetching data from Deriv...")
    df = conn.get_historical_bars(symbol, cfg.ltf_timeframe, start, end)
    print(f"Fetched {len(df)} bars, {df.index.min()} to {df.index.max()}" if not df.empty else "No data returned.")
    if df.empty:
        return [], df

    df_signals = generate_signals(df, cfg)
    trades = run_backtest(df_signals, cfg)

    summary = summarize_trades(trades, cfg)
    print(f"--- {symbol} results ---")
    for k, v in summary.items():
        print(f"{k}: {v}")

    return trades, df


def main():
    years_back = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5

    base_cfg = StrategyConfig()
    gold_cfg = make_gold_config(base_cfg)

    conn = DerivConnector()
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=int(years_back * 365))

    print(f"Backtesting EUR/USD + XAU/USD combined, last ~{years_back} year(s)")
    print(f"Range: {start} to {end}")
    print("This fetches two full instruments' worth of 1-min data - expect "
          "this to take twice as long as a single-instrument run.\n")

    eur_trades, _ = run_instrument(conn, "EURUSD", base_cfg, start, end)
    gold_trades, _ = run_instrument(conn, "XAUUSD", gold_cfg, start, end)

    all_rows = []
    for t in eur_trades:
        all_rows.append({
            "instrument": "EURUSD", "entry_time": t.entry_time,
            "direction": t.direction, "entry_price": t.entry_price,
            "exit_time": t.exit_time, "exit_price": t.exit_price,
            "reason": t.exit_reason, "r_multiple": round(t.r_multiple, 3),
        })
    for t in gold_trades:
        all_rows.append({
            "instrument": "XAUUSD", "entry_time": t.entry_time,
            "direction": t.direction, "entry_price": t.entry_price,
            "exit_time": t.exit_time, "exit_price": t.exit_price,
            "reason": t.exit_reason, "r_multiple": round(t.r_multiple, 3),
        })

    print("\n=== COMBINED (EUR/USD + XAU/USD) ===")
    if not all_rows:
        print("No trades on either instrument in this period.")
        return

    combined_df = pd.DataFrame(all_rows).sort_values("entry_time")
    total_trades = len(combined_df)
    wins = (combined_df["r_multiple"] > 0).sum()
    losses = (combined_df["r_multiple"] < 0).sum()
    breakevens = (combined_df["r_multiple"] == 0).sum()
    total_r = combined_df["r_multiple"].sum()
    win_rate = 100 * wins / total_trades if total_trades else 0

    print(f"num_trades: {total_trades}  (EUR/USD: {len(eur_trades)}, XAU/USD: {len(gold_trades)})")
    print(f"wins: {wins}")
    print(f"losses: {losses}")
    print(f"breakevens: {breakevens}")
    print(f"win_rate_pct: {round(win_rate, 1)}")
    print(f"total_r: {round(total_r, 2)}")
    print(f"avg_r_per_trade: {round(total_r / total_trades, 3)}")

    print("\n--- Itemized trade list (chronological, both instruments) ---")
    for i, row in enumerate(combined_df.itertuples(index=False), 1):
        r = 0.0 if abs(row.r_multiple) < 1e-9 else row.r_multiple  # avoid "-0.00"
        if row.reason == "target":
            label = "WIN"
        elif row.reason == "breakeven":
            label = "BREAKEVEN"
        else:
            label = "LOSS"
        direction_str = "LONG" if row.direction == 1 else "SHORT"
        print(f"{i}. {label:10s} [{row.instrument}] {row.entry_time}  "
              f"{direction_str:5s} entry={row.entry_price:.5f} "
              f"exit={row.exit_price:.5f}  R={r:+.2f}")

    combined_df.to_csv("combined_backtest_trades.csv", index=False)
    print(f"\nFull combined trade log saved to combined_backtest_trades.csv")


if __name__ == "__main__":
    main()
