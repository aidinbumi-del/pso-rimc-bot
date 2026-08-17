"""
Sanity test for paper_broker.py logic, without needing a live MT5
connection. Simulates opening a position and walking it through a
breakeven-then-target scenario.
"""
import pandas as pd
from datetime import datetime, timedelta
from config import StrategyConfig
from paper_broker import PaperAccount

cfg = StrategyConfig()
cfg.risk_per_trade_pct = 1.0
account = PaperAccount(cfg, starting_equity=10000.0, log_path="/tmp/test_paper_trades.csv")

t0 = datetime(2026, 1, 5, 8, 30)

# Open a short position
account.open_position(
    direction=-1, entry_time=t0, entry_price=1.1050,
    stop_price=1.1055, target_price=1.1025,
)
assert account.position is not None
assert account.can_open_new_trade(t0.date()) is False  # already 1 open

# Simulate a bar that triggers breakeven (price takes a prior swing low)
account.update_breakeven(prior_extreme=1.1040, current_high=1.1046, current_low=1.1039)
assert account.position.moved_to_be is True
assert account.position.stop_price == 1.1050  # moved to entry
print("Breakeven trigger: OK")

# Simulate a bar that hits the (now-breakeven) stop
account.check_exit(t0 + timedelta(minutes=5), bar_high=1.1051, bar_low=1.1048)
assert account.position is None
assert account.closed_trades[-1]["reason"] == "breakeven"
assert account.closed_trades[-1]["pnl"] == 0 or abs(account.closed_trades[-1]["pnl"]) < 1e-6
print("Breakeven exit: OK, pnl ~= 0, equity unchanged:", account.equity)

# Open + hit target cleanly
account.open_position(
    direction=1, entry_time=t0 + timedelta(hours=1), entry_price=1.1030,
    stop_price=1.1025, target_price=1.1055,
)
account.check_exit(t0 + timedelta(hours=1, minutes=10), bar_high=1.1060, bar_low=1.1032)
assert account.position is None
assert account.closed_trades[-1]["reason"] == "target"
assert account.closed_trades[-1]["pnl"] > 0
print("Target exit: OK, pnl:", account.closed_trades[-1]["pnl"])

print("\nSummary:", account.summary())
print("\nAll paper_broker sanity checks passed.")
