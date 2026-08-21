"""
Combines HTF bias, LTF location filter, and RIMC breakout/mitigation
detection into concrete entry signals with stop/target levels.
"""
import numpy as np
import pandas as pd
from config import StrategyConfig
from structure import (
    detect_ranges, detect_breakouts, compute_location,
    classify_market_regime, classify_swing_strength,
)


def resample_htf(df_ltf: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    htf = df_ltf.resample(cfg.htf_timeframe).agg(agg).dropna()
    return htf


def compute_htf_context(df_ltf: pd.DataFrame, cfg: StrategyConfig):
    """
    Returns (bias_ltf, regime_ltf): both Series aligned to df_ltf's index.
    bias_ltf: prevailing HTF bias (1 bullish, -1 bearish, 0 none), based
    on the most recent HTF breakout.
    regime_ltf: 'trending' or 'consolidation', based on whether the HTF
    is currently inside a detected range (see classify_market_regime).
    """
    htf = resample_htf(df_ltf, cfg)
    htf = detect_ranges(htf, cfg)
    htf = detect_breakouts(htf, cfg)

    bias = htf["breakout_dir"].replace(0, np.nan).ffill().fillna(0)
    bias_ltf = bias.reindex(df_ltf.index, method="ffill").fillna(0)

    regime = classify_market_regime(htf)
    regime_ltf = regime.reindex(df_ltf.index, method="ffill").fillna("trending")

    return bias_ltf, regime_ltf


def compute_htf_bias(df_ltf: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """Kept for backward compatibility - use compute_htf_context() for
    both bias and regime together without resampling twice."""
    bias_ltf, _ = compute_htf_context(df_ltf, cfg)
    return bias_ltf


def in_session(ts: pd.Timestamp, cfg: StrategyConfig) -> bool:
    """If ts is timezone-aware (e.g. Deriv/OANDA data, which is UTC),
    converts properly to Europe/London - this automatically handles the
    BST/GMT switch, unlike a fixed hour offset. If ts is naive (MT5 data,
    or backtest data already in London time), falls back to the manual
    broker_utc_offset_hours shift, since there's no reliable way to know
    a naive timestamp's DST status without that broker-specific info."""
    if ts.tzinfo is not None:
        ts_london = ts.tz_convert("Europe/London")
    else:
        ts_london = ts - pd.Timedelta(hours=cfg.broker_utc_offset_hours)
    start = ts_london.replace(hour=cfg.session_start_hour,
                               minute=cfg.session_start_minute, second=0, microsecond=0)
    end = ts_london.replace(hour=cfg.session_end_hour,
                             minute=cfg.session_end_minute, second=0, microsecond=0)
    return start <= ts_london <= end and ts_london.dayofweek in cfg.trading_days


def generate_signals(df_ltf: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Main signal pipeline. Returns df_ltf with added columns:
    htf_bias, market_regime, location, setup_valid, direction,
    entry_price, stop_price, target_price, swing_strong
    """
    out = df_ltf.copy()
    htf_bias, htf_regime = compute_htf_context(out, cfg)
    out["htf_bias"] = htf_bias

    out = detect_ranges(out, cfg)
    out = detect_breakouts(out, cfg)
    out = compute_location(out, cfg, regime=htf_regime)

    direction = np.zeros(len(out), dtype=int)
    entry_price = np.full(len(out), np.nan)
    stop_price = np.full(len(out), np.nan)
    target_price = np.full(len(out), np.nan)
    setup_valid = np.zeros(len(out), dtype=bool)
    swing_strong = np.full(len(out), True)

    closes = out["close"].values
    highs = out["high"].values
    lows = out["low"].values
    b_dir = out["breakout_dir"].values
    b_high = out["breakout_range_high"].values
    b_low = out["breakout_range_low"].values
    b_range_start = out["breakout_range_start"].values
    htf_bias_arr = out["htf_bias"].values
    location = out["location"].values
    index = out.index

    pip = cfg.pip_size
    max_stop = cfg.max_stop_pips * pip
    min_stop = cfg.min_stop_pips * pip
    stop_buf = cfg.stop_buffer_pips * pip

    for i in range(len(out)):
        ts = index[i]
        if not in_session(ts, cfg):
            continue

        d = b_dir[i]
        if d == 0:
            continue

        # Must align with HTF bias.
        if htf_bias_arr[i] == 0 or d != htf_bias_arr[i]:
            continue

        # Location filter: shorts only from premium, longs only from discount.
        # (Threshold itself already adapts to trending vs consolidation
        # regime inside compute_location.)
        if d == 1 and location[i] != "discount":
            continue
        if d == -1 and location[i] != "premium":
            continue

        # This is a fresh breakout bar -> mitigation entry: enter back at
        # the edge of the broken range once price returns to it (we treat
        # the breakout bar itself as marking the setup; entry triggers on
        # this bar's close for simplicity of a vectorized-ish backtest —
        # a more precise version would watch subsequent bars for the
        # actual pullback fill).
        if d == 1:
            entry = b_high[i]  # buy back at top of broken range (discount side)
            stop = b_low[i] - stop_buf
            is_high_boundary = False  # the LOW of the range is the stop boundary
        else:
            entry = b_low[i]  # sell back at bottom of broken range (premium side)
            stop = b_high[i] + stop_buf
            is_high_boundary = True  # the HIGH of the range is the stop boundary

        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or stop_dist > max_stop or stop_dist < min_stop:
            continue

        # Strong vs weak swing point filter (NJAT Telegram material):
        # only trust a tight stop beyond a range boundary that shows a
        # sharp, single rejection rather than multiple slow "stacked"
        # touches.
        strong = classify_swing_strength(
            out, i, int(b_range_start[i]), is_high_boundary, cfg
        )
        swing_strong[i] = strong
        if cfg.require_strong_swing_filter and not strong:
            continue

        target = entry + cfg.target_rr * stop_dist * d

        direction[i] = d
        entry_price[i] = entry
        stop_price[i] = stop
        target_price[i] = target
        setup_valid[i] = True

    out["direction"] = direction
    out["entry_price"] = entry_price
    out["stop_price"] = stop_price
    out["target_price"] = target_price
    out["setup_valid"] = setup_valid
    out["swing_strong"] = swing_strong
    return out
