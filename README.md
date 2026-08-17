# PSO + RIMC Strategy Bot

Reconstructed from YouTube transcripts of a forex trading channel (see
STRATEGY_SPEC.md for the full rule set and what's a documented guess vs.
an explicit rule from the source material).

## Architecture (Deriv + TradingView cross-check + mobile dashboard)

**Broker note**: OANDA does not accept Zimbabwe (or several other
countries) — the primary path here uses **Deriv** instead, which is
available in Zimbabwe. An OANDA path (`oanda_connector.py`,
`live_bot_oanda.py`) is kept in the repo in case you ever trade from a
supported country, but `live_bot_deriv.py` is the one to actually run.

- **Data**: Deriv's public WebSocket API (`deriv_connector.py`) — no
  account or token needed for price data, no desktop terminal, runs on
  any lightweight always-on host (a free cloud tier is enough). Deriv's
  live trading products (multiplier/CFD contracts) differ from OANDA/MT5's
  simple market-order model, but that only matters once you build real
  order placement later — paper trading only needs price data, which
  works identically.
- **Cross-check**: a TradingView Pine Script (`pso_rimc_crosscheck.pine`)
  mirrors the same detection logic and fires webhook alerts
  (`tradingview_webhook.py`) as an independent second opinion. Whether
  these gate entries or just get logged is controlled by
  `config.require_tv_confirmation`.
- **Monitoring**: a mobile-friendly dashboard (`dashboard.py`) on port
  5006 — open it in your phone's browser to see equity, open position,
  and recent trades, auto-refreshing every 10s.
- **Execution today**: paper trading only (`paper_broker.py`) — simulated
  money, real live OANDA prices. No real order is ever sent.

An MT5-based path (`mt5_connector.py`, `live_bot.py`) also exists if you
ever want to switch to a broker that only offers MT5 — it needs a desktop
terminal running somewhere, unlike the OANDA path.

## Files

- `STRATEGY_SPEC.md` — the full strategy rules and defaults.
- `config.py` — every tunable threshold in one place.
- `structure.py` / `signals.py` — range/breakout/location/RIMC detection
  and entry signal generation. Shared by the backtest AND the live bot.
- `backtest.py`, `run_example.py` — historical backtest engine + runner.
- `deriv_connector.py` — live price data via Deriv's public WebSocket API
  (no account/token needed for this).
- `pso_rimc_crosscheck.pine` — TradingView Pine Script port of the same
  detection logic, for independent alert-based cross-checking.
- `tradingview_webhook.py` — local server that receives TradingView alerts.
- `dashboard.py` — mobile web dashboard.
- `paper_broker.py` — simulated account: equity, open position, breakeven
  management, CSV trade log.
- `live_bot_deriv.py` — **the main entry point**: ties Deriv + TradingView
  cross-check + dashboard + paper trading together.
- `oanda_connector.py`, `live_bot_oanda.py` — alternate OANDA-based path
  (kept in case you ever trade from a country OANDA supports).
- `mt5_connector.py`, `live_bot.py` — alternate MT5-based path (needs a
  desktop terminal; kept in case you switch to an MT5 broker like Exness,
  HFM, or XM, which do accept Zimbabwe).
- `test_paper_broker.py`, `test_oanda_connector.py`, `test_deriv_connector.py`
  — offline logic tests (no live connection needed) — **all currently
  passing**.

## Setup (Deriv + TradingView path)

1. `pip install -r requirements.txt` (no Deriv account needed for this —
   the price data used is public).
2. (Optional, for TradingView cross-check) Add `pso_rimc_crosscheck.pine`
   as a new Pine Script indicator on a TradingView EUR/USD 1-min chart,
   then create an alert on it with webhook delivery pointed at
   `http://<your-host>:5005/webhook`. Real-time 1-min alerts typically
   need a paid TradingView plan (Essential tier or above).
3. Deploy `live_bot_deriv.py` to a small always-on host — a free tier on
   Render, Railway, or Fly.io is enough for this workload. Locally for
   testing: `python live_bot_deriv.py`.
4. Open `http://<your-host>:5006` in your phone's browser.

## What "paper trading" means here

The bot watches real live OANDA prices and applies the exact same
entry/stop/target/breakeven logic as the backtest, but every trade is
simulated — no real order is ever sent, no real money moves. It's the
standard middle step between a historical backtest and live capital:
backtest tells you if the logic makes sense on the past, paper trading
tells you if it survives real-time execution (spread, gaps, actual price
behavior) before anything real is at risk.

## Path to real money (please read this)

You mentioned wanting to go live if paper trading proves profitable. A
few things worth being direct about before you do:

1. **Paper trading has no slippage beyond what OANDA quotes live** — real
   fills, especially on 2-5 pip stops, can differ meaningfully from paper
   fills. A strategy that's profitable on paper can lose money live purely
   from execution friction.
2. **Run it for weeks, not days.** The source strategy explicitly expects
   losing streaks and breakeven streaks as normal — a short paper run can
   look great or terrible by chance alone. You want enough trades (dozens,
   ideally 100+) before drawing conclusions.
3. **When you do go live**, `oanda_connector.place_market_order()` exists
   but is intentionally not wired into `live_bot_oanda.py`. Wiring it in
   is a deliberate, separate step you should take consciously — start
   with the smallest position size your broker allows, on a small amount
   of capital you can afford to lose entirely.
4. I'm not a financial advisor and this isn't financial advice — the
   above is just responsible-engineering practice, not a guarantee the
   strategy works. Forex trading, especially at 1-minute execution with
   3-5 pip stops, carries real and substantial risk of loss regardless of
   how carefully the code is written.

## What's been verified vs. what you still need to confirm

**Verified by me (offline, automated tests, all passing):**
- Range/breakout/location/RIMC detection logic (`run_example.py` backtest)
- A previously-real bug where a breakeven-then-target trade was
  misrecorded as a 0R breakeven — found and fixed, confirmed with a
  reproduction test
- Paper account math: position sizing, breakeven stop movement, exit
  logic, equity tracking (`test_paper_broker.py`)
- OANDA request formatting and response parsing, including that sell
  orders correctly send negative units and incomplete/forming candles are
  correctly excluded (`test_oanda_connector.py`)
- Deriv candle and tick response parsing, including correct timestamp
  conversion and clear error handling on empty responses
  (`test_deriv_connector.py`)
- Dashboard renders equity/position/trade log correctly from live state
- TradingView cross-check confirmation logic (matching vs. mismatched
  direction alerts)

**Not verified by me — I have no network access or live accounts, so
these are yours to confirm on first run:**
- That the actual live Deriv WebSocket connection works from your host
  (the request/response format is correct per Deriv's docs, but I
  couldn't make a real call)
- That live Deriv candle data matches what you'd expect on a real chart
- (If you use the OANDA path from a supported country instead) that your
  OANDA token/account ID authenticate successfully
- That the TradingView Pine Script compiles and fires alerts as expected
  on TradingView's own editor (I can't run Pine Script myself)
- Broker server timezone offset (`broker_utc_offset_hours` in config.py)
  confirm this against a real live candle timestamp before trusting the
  session window
- All the discretionary-judgment gaps noted in STRATEGY_SPEC.md (what
  counts as a "range", a "strong rejection", etc.) still apply — the live
  bot uses the same detection logic as the backtest, so it inherits the
  same approximation gap versus how the human trader would actually read
  the chart.
