"""
Combines HTF bias, LTF location filter, and RIMC breakout/mitigation
detection into concrete entry signals with stop/target levels.
"""
import numpy as np
import pandas as pd
from config import StrategyConfig
from structure import detect_ranges, detect_breakouts, compute_location


def resample_htf(df_ltf: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    htf = df_ltf.resample(cfg.htf_timeframe).agg(agg).dropna()
    return htf


def compute_htf_bias(df_ltf: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """
    Returns a Series aligned to df_ltf's index giving the prevailing HTF
    bias (1 = bullish, -1 = bearish, 0 = none) at each LTF bar, based on
    the most recent HTF breakout.
    """
    htf = resample_htf(df_ltf, cfg)
    htf = detect_ranges(htf, cfg)
    htf = detect_breakouts(htf, cfg)

    # Forward-fill the most recent non-zero breakout direction on the HTF
    # index, then reindex onto the LTF index.
    bias = htf["breakout_dir"].replace(0, np.nan).ffill().fillna(0)
    bias_ltf = bias.reindex(df_ltf.index, method="ffill").fillna(0)
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
    htf_bias, location, ltf_breakout_dir, setup_valid, direction,
    entry_price, stop_price, target_price
    """
    out = df_ltf.copy()
    out["htf_bias"] = compute_htf_bias(out, cfg)

    out = detect_ranges(out, cfg)
    out = detect_breakouts(out, cfg)
    out = compute_location(out, cfg)

    direction = np.zeros(len(out), dtype=int)
    entry_price = np.full(len(out), np.nan)
    stop_price = np.full(len(out), np.nan)
    target_price = np.full(len(out), np.nan)
    setup_valid = np.zeros(len(out), dtype=bool)

    closes = out["close"].values
    highs = out["high"].values
    lows = out["low"].values
    b_dir = out["breakout_dir"].values
    b_high = out["breakout_range_high"].values
    b_low = out["breakout_range_low"].values
    htf_bias = out["htf_bias"].values
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
        if htf_bias[i] == 0 or d != htf_bias[i]:
            continue

        # Location filter: shorts only from premium, longs only from discount.
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
        else:
            entry = b_low[i]  # sell back at bottom of broken range (premium side)
            stop = b_high[i] + stop_buf

        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or stop_dist > max_stop or stop_dist < min_stop:
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
    return out
