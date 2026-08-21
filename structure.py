"""
Price-structure detection primitives: ATR, ranges, breakouts, swings,
premium/discount location, market regime, and swing-strength
classification.

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

    Returns df with added columns: atr, range_high, range_low, in_range,
    range_run_start (bar-index where the current contiguous in-range
    streak began - used later for swing-strength classification).
    """
    out = df.copy()
    out["atr"] = compute_atr(out, cfg.atr_period)

    roll_high = out["high"].rolling(cfg.range_min_bars).max()
    roll_low = out["low"].rolling(cfg.range_min_bars).min()
    spread = roll_high - roll_low

    out["range_high"] = roll_high
    out["range_low"] = roll_low
    in_range = (spread <= (cfg.range_max_atr_mult * out["atr"])).values
    out["in_range"] = in_range

    n = len(out)
    run_start = np.full(n, -1, dtype=int)
    current_start = -1
    for i in range(n):
        if in_range[i]:
            if current_start == -1:
                current_start = max(0, i - cfg.range_min_bars + 1)
            run_start[i] = current_start
        else:
            current_start = -1
    out["range_run_start"] = run_start
    return out


def detect_breakouts(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """
    Given a df already processed by detect_ranges, flags breakout bars:
    a close beyond the most recent confirmed range's high/low by at least
    breakout_atr_mult * ATR, immediately following a bar where in_range
    was True.

    Adds columns: breakout_dir (1 = bullish, -1 = bearish, 0 = none),
    breakout_range_high, breakout_range_low (the range that was broken),
    breakout_range_start (bar-index the broken range began - used for
    swing-strength classification).
    """
    out = df.copy()
    breakout_dir = np.zeros(len(out), dtype=int)
    b_high = np.full(len(out), np.nan)
    b_low = np.full(len(out), np.nan)
    b_range_start = np.full(len(out), -1, dtype=int)

    last_range_high = np.nan
    last_range_low = np.nan
    last_range_start = -1
    was_in_range = False

    highs = out["high"].values
    lows = out["low"].values
    closes = out["close"].values
    atrs = out["atr"].values
    in_range = out["in_range"].values
    range_high = out["range_high"].values
    range_low = out["range_low"].values
    range_run_start = out["range_run_start"].values

    for i in range(len(out)):
        if in_range[i]:
            last_range_high = range_high[i]
            last_range_low = range_low[i]
            last_range_start = range_run_start[i]
            was_in_range = True
            continue

        if was_in_range and not np.isnan(atrs[i]):
            thresh = cfg.breakout_atr_mult * atrs[i]
            if closes[i] > last_range_high + thresh:
                breakout_dir[i] = 1
                b_high[i] = last_range_high
                b_low[i] = last_range_low
                b_range_start[i] = last_range_start
                was_in_range = False
            elif closes[i] < last_range_low - thresh:
                breakout_dir[i] = -1
                b_high[i] = last_range_high
                b_low[i] = last_range_low
                b_range_start[i] = last_range_start
                was_in_range = False

    out["breakout_dir"] = breakout_dir
    out["breakout_range_high"] = b_high
    out["breakout_range_low"] = b_low
    out["breakout_range_start"] = b_range_start
    return out


def classify_market_regime(htf_df: pd.DataFrame) -> pd.Series:
    """
    Returns a Series aligned to htf_df's index: 'consolidation' if the
    HTF bar is itself inside a detected range (htf_df['in_range'] is
    True), 'trending' otherwise.

    This is a proxy for NJAT's qualitative trending-vs-consolidation
    distinction - their material shows this visually ("slow sideways
    price action" vs a clear directional ABCD leg) rather than giving an
    exact formula. Requires htf_df to have already gone through
    detect_ranges().
    """
    regime = np.where(htf_df["in_range"], "consolidation", "trending")
    return pd.Series(regime, index=htf_df.index)


def compute_location(df: pd.DataFrame, cfg: StrategyConfig,
                      regime: pd.Series = None) -> pd.DataFrame:
    """
    Computes the rolling "A to B" swing leg (high/low over
    swing_lookback_bars) and classifies each bar's close as premium,
    discount, or neutral.

    Behavior depends on market regime (NJAT's official material gives
    different rules for each):
    - TRENDING (default when regime is None): 50% premium/discount
      split with mid_zone_buffer_pct dead zone (as before).
    - CONSOLIDATION: only the outer consolidation_edge_pct (e.g. top/
      bottom 25%) counts as premium/discount; the middle is "neutral" -
      NJAT calls this middle zone "the slaughterhouse".

    Adds columns: swing_high, swing_low, swing_mid, market_regime,
    location (one of "premium", "discount", "neutral")
    """
    out = df.copy()
    out["swing_high"] = out["high"].rolling(cfg.swing_lookback_bars).max()
    out["swing_low"] = out["low"].rolling(cfg.swing_lookback_bars).min()
    out["swing_mid"] = (out["swing_high"] + out["swing_low"]) / 2
    swing_range = out["swing_high"] - out["swing_low"]

    if regime is None:
        regime_aligned = pd.Series("trending", index=out.index)
    else:
        regime_aligned = regime.reindex(out.index).fillna("trending")
    is_trending = (regime_aligned == "trending").values

    buffer = swing_range * cfg.mid_zone_buffer_pct
    upper_mid = (out["swing_mid"] + buffer / 2).values
    lower_mid = (out["swing_mid"] - buffer / 2).values

    edge = cfg.consolidation_edge_pct
    top_edge_level = (out["swing_high"] - swing_range * edge).values
    bottom_edge_level = (out["swing_low"] + swing_range * edge).values

    close = out["close"].values
    location = np.full(len(out), "neutral", dtype=object)

    trend_premium = is_trending & (close > upper_mid)
    trend_discount = is_trending & (close < lower_mid)
    consol_premium = (~is_trending) & (close >= top_edge_level)
    consol_discount = (~is_trending) & (close <= bottom_edge_level)

    location[trend_premium | consol_premium] = "premium"
    location[trend_discount | consol_discount] = "discount"

    out["market_regime"] = regime_aligned.values
    out["location"] = location
    return out


def classify_swing_strength(df: pd.DataFrame, breakout_idx: int,
                             range_start_idx: int, is_high: bool,
                             cfg: StrategyConfig) -> bool:
    """
    Classifies whether the range boundary being broken (a high, if
    is_high=True; a low if False) is a "strong" or "weak" swing point,
    per NJAT's Telegram material: a strong high/low forms from a single
    fast, sharp rejection and holds up as support/resistance; a weak one
    forms slowly with multiple "stacked" touches near the same level and
    price is likely to shoot straight through it.

    This is my own concrete proxy for that qualitative rule (NJAT
    describes it by speed/aggression, not an exact formula): counts how
    many bars within the range window came within
    stacked_touch_atr_mult * ATR of the extreme. Many close touches =
    weak (slow grind); few (e.g. one sharp spike) = strong.

    Returns True if 'strong' (safe to trust for a tight stop), False if
    'weak' (source material suggests price is more likely to break
    through it - a signal to be cautious, not necessarily an automatic
    reject unless cfg.require_strong_swing_filter is set).
    """
    if range_start_idx < 0 or range_start_idx >= breakout_idx:
        return True  # not enough history to judge - don't block the trade

    window = df.iloc[range_start_idx:breakout_idx]
    if window.empty:
        return True

    atr = df["atr"].iloc[breakout_idx]
    if pd.isna(atr) or atr == 0:
        return True

    tolerance = cfg.stacked_touch_atr_mult * atr
    if is_high:
        extreme = window["high"].max()
        touches = int((extreme - window["high"] <= tolerance).sum())
    else:
        extreme = window["low"].min()
        touches = int((window["low"] - extreme <= tolerance).sum())

    return touches <= cfg.max_stacked_touches_for_strong


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
