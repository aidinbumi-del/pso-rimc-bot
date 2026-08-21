"""
Bar-by-bar backtest engine. Walks forward through the LTF data, opens
trades on valid setups (respecting max trades per session), simulates
stop/target/breakeven management, and records results.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from config import StrategyConfig
from structure import find_prior_swing_extreme


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: int  # 1 long, -1 short
    entry_price: float
    initial_stop: float  # fixed at entry, NEVER mutated - used for R-multiple calc
    target: float
    current_stop: float = None  # mutated by breakeven management; used for exit checks
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "target", "stop", "breakeven"
    moved_to_be: bool = False

    def __post_init__(self):
        if self.current_stop is None:
            self.current_stop = self.initial_stop

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.initial_stop)
        if risk == 0 or self.exit_price is None:
            return 0.0
        pnl = (self.exit_price - self.entry_price) * self.direction
        return pnl / risk


def run_backtest(df_signals: pd.DataFrame, cfg: StrategyConfig) -> List[Trade]:
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None
    session_trade_count = {}  # date -> count

    idx = df_signals.index
    highs = df_signals["high"].values
    lows = df_signals["low"].values
    setup_valid = df_signals["setup_valid"].values
    direction_arr = df_signals["direction"].values
    entry_arr = df_signals["entry_price"].values
    stop_arr = df_signals["stop_price"].values
    target_arr = df_signals["target_price"].values

    for i in range(len(df_signals)):
        ts = idx[i]
        day_key = ts.date()

        # --- Manage open trade first ---
        if open_trade is not None:
            hi, lo = highs[i], lows[i]

            # Break-even management: once price has moved favorably enough
            # to take out the prior internal swing extreme, move stop to
            # entry.
            if cfg.use_breakeven_management and not open_trade.moved_to_be:
                prior_extreme = find_prior_swing_extreme(
                    df_signals, i, open_trade.direction
                )
                if prior_extreme is not None:
                    if open_trade.direction == 1 and hi >= prior_extreme:
                        open_trade.current_stop = max(
                            open_trade.current_stop, open_trade.entry_price
                        )
                        open_trade.moved_to_be = True
                    elif open_trade.direction == -1 and lo <= prior_extreme:
                        open_trade.current_stop = min(
                            open_trade.current_stop, open_trade.entry_price
                        )
                        open_trade.moved_to_be = True

            # Check stop/target hits this bar.
            stop = open_trade.current_stop
            target = open_trade.target
            hit_stop = (lo <= stop) if open_trade.direction == 1 else (hi >= stop)
            hit_target = (hi >= target) if open_trade.direction == 1 else (lo <= target)

            if hit_stop and hit_target:
                # Conservative assumption: stop hit first if both in same bar.
                open_trade.exit_time = ts
                open_trade.exit_price = stop
                open_trade.exit_reason = "breakeven" if open_trade.moved_to_be else "stop"
                trades.append(open_trade)
                open_trade = None
            elif hit_stop:
                open_trade.exit_time = ts
                open_trade.exit_price = stop
                open_trade.exit_reason = "breakeven" if open_trade.moved_to_be else "stop"
                trades.append(open_trade)
                open_trade = None
            elif hit_target:
                open_trade.exit_time = ts
                open_trade.exit_price = target
                open_trade.exit_reason = "target"
                trades.append(open_trade)
                open_trade = None

        # --- Consider opening a new trade ---
        if open_trade is None and setup_valid[i]:
            count = session_trade_count.get(day_key, 0)
            if count < cfg.max_trades_per_session:
                open_trade = Trade(
                    entry_time=ts,
                    direction=int(direction_arr[i]),
                    entry_price=float(entry_arr[i]),
                    initial_stop=float(stop_arr[i]),
                    target=float(target_arr[i]),
                )
                session_trade_count[day_key] = count + 1

    return trades


def summarize_trades(trades: List[Trade], cfg: StrategyConfig) -> dict:
    if not trades:
        return {"num_trades": 0}

    r_values = [t.r_multiple for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    breakevens = [r for r in r_values if r == 0]

    total_r = sum(r_values)
    win_rate = len(wins) / len(trades) if trades else 0

    return {
        "num_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate_pct": round(win_rate * 100, 1),
        "total_r": round(total_r, 2),
        "avg_r_per_trade": round(total_r / len(trades), 3),
        "target_rr_used": cfg.target_rr,
    }


def classify_outcome(trade: Trade) -> str:
    """Returns 'WIN', 'BREAKEVEN', or 'LOSS' based on exit reason -
    matches the classification already used in summarize_trades (by
    r_multiple sign) but as a per-trade label."""
    if trade.exit_reason == "target":
        return "WIN"
    elif trade.exit_reason == "breakeven":
        return "BREAKEVEN"
    else:
        return "LOSS"


def print_trade_list(trades: List[Trade], instrument_labels: List[str] = None) -> None:
    """Prints a numbered, itemized list of every trade with its outcome
    (WIN/BREAKEVEN/LOSS), direction, entry/exit prices, and R-multiple -
    the per-trade detail behind the aggregate summary stats.

    instrument_labels: optional list (same length as trades) to prefix
    each line with an instrument name, for combined multi-instrument runs.
    """
    if not trades:
        print("No trades to list.")
        return

    for i, t in enumerate(trades, 1):
        label = classify_outcome(t)
        direction_str = "LONG" if t.direction == 1 else "SHORT"
        prefix = f"[{instrument_labels[i-1]}] " if instrument_labels else ""
        exit_price_str = f"{t.exit_price:.5f}" if t.exit_price is not None else "N/A"
        r_display = 0.0 if abs(t.r_multiple) < 1e-9 else t.r_multiple  # avoid "-0.00"
        print(f"{i}. {label:10s} {prefix}{t.entry_time}  {direction_str:5s} "
              f"entry={t.entry_price:.5f} exit={exit_price_str}  "
              f"R={r_display:+.2f}")"""
Bar-by-bar backtest engine. Walks forward through the LTF data, opens
trades on valid setups (respecting max trades per session), simulates
stop/target/breakeven management, and records results.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from config import StrategyConfig
from structure import find_prior_swing_extreme


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: int  # 1 long, -1 short
    entry_price: float
    initial_stop: float  # fixed at entry, NEVER mutated - used for R-multiple calc
    target: float
    current_stop: float = None  # mutated by breakeven management; used for exit checks
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "target", "stop", "breakeven"
    moved_to_be: bool = False

    def __post_init__(self):
        if self.current_stop is None:
            self.current_stop = self.initial_stop

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.initial_stop)
        if risk == 0 or self.exit_price is None:
            return 0.0
        pnl = (self.exit_price - self.entry_price) * self.direction
        return pnl / risk


def run_backtest(df_signals: pd.DataFrame, cfg: StrategyConfig) -> List[Trade]:
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None
    session_trade_count = {}  # date -> count

    idx = df_signals.index
    highs = df_signals["high"].values
    lows = df_signals["low"].values
    setup_valid = df_signals["setup_valid"].values
    direction_arr = df_signals["direction"].values
    entry_arr = df_signals["entry_price"].values
    stop_arr = df_signals["stop_price"].values
    target_arr = df_signals["target_price"].values

    for i in range(len(df_signals)):
        ts = idx[i]
        day_key = ts.date()

        # --- Manage open trade first ---
        if open_trade is not None:
            hi, lo = highs[i], lows[i]

            # Break-even management: once price has moved favorably enough
            # to take out the prior internal swing extreme, move stop to
            # entry.
            if cfg.use_breakeven_management and not open_trade.moved_to_be:
                prior_extreme = find_prior_swing_extreme(
                    df_signals, i, open_trade.direction
                )
                if prior_extreme is not None:
                    if open_trade.direction == 1 and hi >= prior_extreme:
                        open_trade.current_stop = max(
                            open_trade.current_stop, open_trade.entry_price
                        )
                        open_trade.moved_to_be = True
                    elif open_trade.direction == -1 and lo <= prior_extreme:
                        open_trade.current_stop = min(
                            open_trade.current_stop, open_trade.entry_price
                        )
                        open_trade.moved_to_be = True

            # Check stop/target hits this bar.
            stop = open_trade.current_stop
            target = open_trade.target
            hit_stop = (lo <= stop) if open_trade.direction == 1 else (hi >= stop)
            hit_target = (hi >= target) if open_trade.direction == 1 else (lo <= target)

            if hit_stop and hit_target:
                # Conservative assumption: stop hit first if both in same bar.
                open_trade.exit_time = ts
                open_trade.exit_price = stop
                open_trade.exit_reason = "breakeven" if open_trade.moved_to_be else "stop"
                trades.append(open_trade)
                open_trade = None
            elif hit_stop:
                open_trade.exit_time = ts
                open_trade.exit_price = stop
                open_trade.exit_reason = "breakeven" if open_trade.moved_to_be else "stop"
                trades.append(open_trade)
                open_trade = None
            elif hit_target:
                open_trade.exit_time = ts
                open_trade.exit_price = target
                open_trade.exit_reason = "target"
                trades.append(open_trade)
                open_trade = None

        # --- Consider opening a new trade ---
        if open_trade is None and setup_valid[i]:
            count = session_trade_count.get(day_key, 0)
            if count < cfg.max_trades_per_session:
                open_trade = Trade(
                    entry_time=ts,
                    direction=int(direction_arr[i]),
                    entry_price=float(entry_arr[i]),
                    initial_stop=float(stop_arr[i]),
                    target=float(target_arr[i]),
                )
                session_trade_count[day_key] = count + 1

    return trades


def summarize_trades(trades: List[Trade], cfg: StrategyConfig) -> dict:
    if not trades:
        return {"num_trades": 0}

    r_values = [t.r_multiple for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    breakevens = [r for r in r_values if r == 0]

    total_r = sum(r_values)
    win_rate = len(wins) / len(trades) if trades else 0

    return {
        "num_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate_pct": round(win_rate * 100, 1),
        "total_r": round(total_r, 2),
        "avg_r_per_trade": round(total_r / len(trades), 3),
        "target_rr_used": cfg.target_rr,
    }


def classify_outcome(trade: Trade) -> str:
    """Returns 'WIN', 'BREAKEVEN', or 'LOSS' based on exit reason -
    matches the classification already used in summarize_trades (by
    r_multiple sign) but as a per-trade label."""
    if trade.exit_reason == "target":
        return "WIN"
    elif trade.exit_reason == "breakeven":
        return "BREAKEVEN"
    else:
        return "LOSS"


def print_trade_list(trades: List[Trade], instrument_labels: List[str] = None) -> None:
    """Prints a numbered, itemized list of every trade with its outcome
    (WIN/BREAKEVEN/LOSS), direction, entry/exit prices, and R-multiple -
    the per-trade detail behind the aggregate summary stats.

    instrument_labels: optional list (same length as trades) to prefix
    each line with an instrument name, for combined multi-instrument runs.
    """
    if not trades:
        print("No trades to list.")
        return

    for i, t in enumerate(trades, 1):
        label = classify_outcome(t)
        direction_str = "LONG" if t.direction == 1 else "SHORT"
        prefix = f"[{instrument_labels[i-1]}] " if instrument_labels else ""
        exit_price_str = f"{t.exit_price:.5f}" if t.exit_price is not None else "N/A"
        r_display = 0.0 if abs(t.r_multiple) < 1e-9 else t.r_multiple  # avoid "-0.00"
        print(f"{i}. {label:10s} {prefix}{t.entry_time}  {direction_str:5s} "
              f"entry={t.entry_price:.5f} exit={exit_price_str}  "
              f"R={r_display:+.2f}")
