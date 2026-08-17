"""
Offline test of deriv_connector.py's response-parsing logic, using
hand-built response dicts matching Deriv's documented API shape (no real
network call). Confirms the parsing is correct - it does NOT confirm a
real live connection works, since that requires actual network access.
"""
import pandas as pd
from deriv_connector import parse_candles_response, parse_tick_response

mock_candle_response = {
    "candles": [
        {"epoch": 1767600000, "open": 1.10500, "high": 1.10520, "low": 1.10490, "close": 1.10510},
        {"epoch": 1767600060, "open": 1.10510, "high": 1.10530, "low": 1.10505, "close": 1.10525},
        {"epoch": 1767600120, "open": 1.10525, "high": 1.10540, "low": 1.10520, "close": 1.10535},
    ]
}

df = parse_candles_response(mock_candle_response)
assert len(df) == 3
assert list(df.columns) == ["open", "high", "low", "close"]
assert isinstance(df.index, pd.DatetimeIndex)
assert df.iloc[0]["close"] == 1.10510
assert df.iloc[-1]["close"] == 1.10535
print("Candle parsing: OK, 3 bars parsed with correct OHLC and timestamps")

mock_tick_response = {
    "history": {
        "prices": [1.10501, 1.10503, 1.10508],
        "times": [1767600000, 1767600001, 1767600002],
    }
}
price = parse_tick_response(mock_tick_response)
assert price == 1.10508
print("Tick parsing: OK, correctly extracted the latest quote")

try:
    parse_tick_response({"history": {"prices": []}})
    print("FAILED: should have raised on empty prices")
except RuntimeError:
    print("Empty tick response handling: OK, raises clearly instead of crashing silently")

print("\nAll deriv_connector offline tests passed.")
