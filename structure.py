"""
Price-structure detection primitives: ATR, ranges, breakouts, swings,
and premium/discount location.

All functions take a pandas DataFrame with columns: open, high, low, close
(and a DatetimeIndex), and the StrategyConfig.
"""
import numpy as np
import pandas as pd
from config import StrategyConfig


def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def detect_ranges(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Flags bars that are the *end* of a detected sideways range, along with
    that range's high/low, using a rolling window: a range is confirmed
    when the high-low spread over `range_min_bars` stays under
    `range_max_atr_mult` * ATR.

    Returns df with added columns: atr, range_high, range_low, in_range
    """
    out = df.copy()
    out["atr"] = compute_atr(out, cfg.atr_period)

    roll_high = out["high"].rolling(cfg.range_min_bars).max()
    roll_low = out["low"].rolling(cfg.range_min_bars).min()
    spread = roll_high - roll_low

    out["range_high"] = roll_high
    out["range_low"] = roll_low
    out["in_range"] = spread <= (cfg.range_max_atr_mult * out["atr"])
    return out


def detect_breakouts(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Given a df already processed by detect_ranges, flags breakout bars:
    a close beyond the most recent confirmed range's high/low by at least
    breakout_atr_mult * ATR, immediately following a bar where in_range
    was True.

    Adds columns: breakout_dir (1 = bullish, -1 = bearish, 0 = none),
    breakout_range_high, breakout_range_low (the range that was broken).
    """
    out = df.copy()
    breakout_dir = np.zeros(len(out), dtype=int)
    b_high = np.full(len(out), np.nan)
    b_low = np.full(len(out), np.nan)

    last_range_high = np.nan
    last_range_low = np.nan
    was_in_range = False

    highs = out["high"].values
    lows = out["low"].values
    closes = out["close"].values
    atrs = out["atr"].values
    in_range = out["in_range"].values
    range_high = out["range_high"].values
    range_low = out["range_low"].values

    for i in range(len(out)):
        if in_range[i]:
            last_range_high = range_high[i]
            last_range_low = range_low[i]
            was_in_range = True
            continue

        if was_in_range and not np.isnan(atrs[i]):
            thresh = cfg.breakout_atr_mult * atrs[i]
            if closes[i] > last_range_high + thresh:
                breakout_dir[i] = 1
                b_high[i] = last_range_high
                b_low[i] = last_range_low
                was_in_range = False
            elif closes[i] < last_range_low - thresh:
                breakout_dir[i] = -1
                b_high[i] = last_range_high
                b_low[i] = last_range_low
                was_in_range = False

    out["breakout_dir"] = breakout_dir
    out["breakout_range_high"] = b_high
    out["breakout_range_low"] = b_low
    return out


def compute_location(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Computes the rolling "A to B" swing leg (high/low over
    swing_lookback_bars) and classifies each bar's close as premium,
    discount, or neutral (mid-zone).

    Adds columns: swing_high, swing_low, swing_mid, location
    (one of "premium", "discount", "neutral")
    """
    out = df.copy()
    out["swing_high"] = out["high"].rolling(cfg.swing_lookback_bars).max()
    out["swing_low"] = out["low"].rolling(cfg.swing_lookback_bars).min()
    out["swing_mid"] = (out["swing_high"] + out["swing_low"]) / 2

    leg_range = out["swing_high"] - out["swing_low"]
    buffer = leg_range * cfg.mid_zone_buffer_pct
    upper_mid = out["swing_mid"] + buffer / 2
    lower_mid = out["swing_mid"] - buffer / 2

    location = np.where(
        out["close"] > upper_mid, "premium",
        np.where(out["close"] < lower_mid, "discount", "neutral")
    )
    out["location"] = location
    return out


def find_prior_swing_extreme(df: pd.DataFrame, idx: int, direction: int,
                              lookback: int = 50):
    """
    For break-even management: find the most recent internal swing
    low (direction=-1, i.e. short trade favor = price making new lows)
    or swing high (direction=1) before position `idx`, within `lookback`
    bars. Simple local-extreme approach (not zigzag-perfect, but workable).
    """
    start = max(0, idx - lookback)
    window = df.iloc[start:idx]
    if window.empty:
        return None
    if direction == -1:
        return window["low"].min()
    else:
        return window["high"].max()
