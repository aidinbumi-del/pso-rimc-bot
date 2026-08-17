"""
Paper trading engine. Tracks a simulated account (starting equity, open
position, closed trade log) driven by live bid/ask prices. No real money
moves. Mirrors the same stop/target/breakeven logic as backtest.py so
paper results are directly comparable to the historical backtest.
"""
import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from config import StrategyConfig


@dataclass
class PaperPosition:
    direction: int  # 1 long, -1 short
    entry_time: datetime
    entry_price: float
    stop_price: float
    target_price: float
    size_units: float
    moved_to_be: bool = False
    prior_extreme_watch: Optional[float] = None  # swing level to watch for BE trigger


class PaperAccount:
    def __init__(self, cfg: StrategyConfig, starting_equity: float = 10000.0,
                 log_path: str = "paper_trades.csv"):
        self.cfg = cfg
        self.equity = starting_equity
        self.starting_equity = starting_equity
        self.position: Optional[PaperPosition] = None
        self.closed_trades = []
        self.session_trade_count = {}
        self.log_path = log_path
        self._ensure_log_file()

    def _ensure_log_file(self):
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "entry_time", "direction", "entry_price", "stop_price",
                    "target_price", "exit_time", "exit_price", "exit_reason",
                    "r_multiple", "pnl", "equity_after"
                ])

    def can_open_new_trade(self, day_key) -> bool:
        if self.position is not None:
            return False
        count = self.session_trade_count.get(day_key, 0)
        return count < self.cfg.max_trades_per_session

    def open_position(self, direction: int, entry_time: datetime,
                       entry_price: float, stop_price: float,
                       target_price: float):
        risk_amount = self.equity * (self.cfg.risk_per_trade_pct / 100.0)
        stop_dist = abs(entry_price - stop_price)
        size_units = risk_amount / stop_dist if stop_dist > 0 else 0

        self.position = PaperPosition(
            direction=direction,
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            size_units=size_units,
        )
        day_key = entry_time.date()
        self.session_trade_count[day_key] = self.session_trade_count.get(day_key, 0) + 1
        print(f"[PAPER] Opened {'LONG' if direction==1 else 'SHORT'} "
              f"@ {entry_price:.5f} stop={stop_price:.5f} target={target_price:.5f} "
              f"size={size_units:.0f} units")

    def update_breakeven(self, prior_extreme: float, current_high: float,
                          current_low: float):
        if self.position is None or not self.cfg.use_breakeven_management:
            return
        if self.position.moved_to_be:
            return
        if self.position.direction == 1 and current_high >= prior_extreme:
            self.position.stop_price = max(self.position.stop_price, self.position.entry_price)
            self.position.moved_to_be = True
            print(f"[PAPER] Moved stop to breakeven ({self.position.entry_price:.5f})")
        elif self.position.direction == -1 and current_low <= prior_extreme:
            self.position.stop_price = min(self.position.stop_price, self.position.entry_price)
            self.position.moved_to_be = True
            print(f"[PAPER] Moved stop to breakeven ({self.position.entry_price:.5f})")

    def check_exit(self, current_time: datetime, bar_high: float, bar_low: float):
        """Check if the open position hits stop or target within this bar's
        high/low range. Assumes stop-first if both hit same bar (conservative)."""
        if self.position is None:
            return

        pos = self.position
        hit_stop = (bar_low <= pos.stop_price) if pos.direction == 1 else (bar_high >= pos.stop_price)
        hit_target = (bar_high >= pos.target_price) if pos.direction == 1 else (bar_low <= pos.target_price)

        if hit_stop:
            self._close(current_time, pos.stop_price,
                        "breakeven" if pos.moved_to_be else "stop")
        elif hit_target:
            self._close(current_time, pos.target_price, "target")

    def _close(self, exit_time: datetime, exit_price: float, reason: str):
        pos = self.position
        pnl = (exit_price - pos.entry_price) * pos.direction * pos.size_units
        risk = abs(pos.entry_price - pos.stop_price) * pos.size_units
        # recompute r using original risk basis is tricky once stop moved to
        # BE; use the entry-to-stop distance at close time as the reference
        r_multiple = pnl / (self.equity * (self.cfg.risk_per_trade_pct / 100.0)) \
            if self.cfg.risk_per_trade_pct > 0 else 0

        self.equity += pnl
        self.closed_trades.append({
            "entry_time": pos.entry_time, "direction": pos.direction,
            "entry_price": pos.entry_price, "exit_time": exit_time,
            "exit_price": exit_price, "reason": reason, "pnl": pnl,
            "r_multiple": r_multiple,
        })

        with open(self.log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                pos.entry_time, pos.direction, pos.entry_price, pos.stop_price,
                pos.target_price, exit_time, exit_price, reason,
                round(r_multiple, 3), round(pnl, 2), round(self.equity, 2)
            ])

        print(f"[PAPER] Closed {reason.upper()} @ {exit_price:.5f} "
              f"PnL={pnl:+.2f} Equity={self.equity:.2f}")
        self.position = None

    def summary(self) -> dict:
        if not self.closed_trades:
            return {"num_trades": 0, "equity": self.equity}
        wins = [t for t in self.closed_trades if t["pnl"] > 0]
        losses = [t for t in self.closed_trades if t["pnl"] < 0]
        return {
            "num_trades": len(self.closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / len(self.closed_trades), 1),
            "starting_equity": self.starting_equity,
            "current_equity": round(self.equity, 2),
            "return_pct": round(100 * (self.equity - self.starting_equity) / self.starting_equity, 2),
        }
