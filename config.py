"""
Tunable parameters for the PSO + RIMC + 1-min entry strategy.

Every threshold here is a documented default, not a value stated exactly
in the source videos (the videos describe these things visually, not
numerically). Tune these against your own data before trusting results.
See STRATEGY_SPEC.md for the reasoning behind each one.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class StrategyConfig:
    # --- Timeframes ---
    # Higher timeframe used for bias / range detection.
    htf_timeframe: str = "4h"
    # Working timeframe for setup + entry (RIMC detection, entries).
    ltf_timeframe: str = "1min"

    # --- Range / breakout detection (used at both HTF and LTF) ---
    # Minimum number of bars required to call something a "range".
    range_min_bars: int = 6
    # A range is defined as N bars whose high-low spread stays within
    # this multiple of ATR (i.e. "not trending").
    range_max_atr_mult: float = 1.5
    # A breakout is confirmed when price closes beyond the range by at
    # least this multiple of ATR.
    breakout_atr_mult: float = 0.5
    # ATR lookback period.
    atr_period: int = 14

    # --- Location / premium-discount filter ---
    # Swing lookback window (bars) used to compute the current A-to-B leg
    # for the premium/discount calculation.
    swing_lookback_bars: int = 100
    # Buffer around the 50% midline treated as "no trade" (as a fraction
    # of the leg's total range, e.g. 0.1 = middle 10% of the leg is dead
    # zone).
    mid_zone_buffer_pct: float = 0.10

    # --- Entry filter ---
    # Reject any setup whose stop distance exceeds this many pips, or
    # falls below the minimum (source video: "I don't go below 2.2").
    max_stop_pips: float = 5.0
    min_stop_pips: float = 2.2
    # Extra buffer added beyond the swing high/low when placing the stop.
    stop_buffer_pips: float = 0.5
    # Pip size for the instrument being traded (0.0001 for most FX pairs,
    # 0.01 for JPY pairs).
    pip_size: float = 0.0001

    # --- Reward / exit ---
    min_rr: float = 5.0
    max_rr: float = 10.0
    # R:R target actually used to place the take-profit order.
    target_rr: float = 5.0

    # --- Break-even management ---
    # Move stop to break-even once price takes out the prior internal
    # swing extreme in the trade's favor.
    use_breakeven_management: bool = True

    # --- Session window (in LONDON time — see broker_utc_offset_hours
    # below for how live-bot data gets converted to match this) ---
    session_start_hour: int = 8
    session_start_minute: int = 0
    session_end_hour: int = 10
    session_end_minute: int = 0
    # MT5 timestamps are in the BROKER's server time, which is usually
    # NOT London time and NOT UTC - it varies by broker and by DST.
    # Set this to (broker_server_time - London_time) in hours so the live
    # bot can convert before checking the session window. You MUST check
    # this against your own broker (compare a live MT5 candle timestamp
    # to the actual London clock) - a wrong offset means the bot silently
    # trades the wrong hours. Backtests on data you've already converted
    # to London time should leave this at 0.
    broker_utc_offset_hours: int = 0

    # --- Live-only safety filter ---
    # Reject a live setup if the current bid/ask spread exceeds this many
    # pips. Source material explicitly describes a loss caused by spread
    # widening during low-liquidity range conditions - this guards against
    # the same failure mode. Not used by the historical backtest (OHLC
    # data has no spread info), only by live_bot.py.
    max_spread_pips: float = 2.0

    # --- Frequency controls ---
    max_trades_per_session: int = 2
    # 0=Monday ... 6=Sunday. Default Mon-Thu per source material.
    trading_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3])

    # --- TradingView cross-check ---
    # If True, a valid setup detected via OANDA data is only actually
    # opened once a TradingView webhook alert has also confirmed the
    # same direction within tv_confirmation_window_minutes. If False,
    # TradingView alerts are logged for comparison but don't gate entries.
    require_tv_confirmation: bool = False
    tv_confirmation_window_minutes: int = 5

    # --- Risk sizing ---
    risk_per_trade_pct: float = 0.75  # percent of account equity
