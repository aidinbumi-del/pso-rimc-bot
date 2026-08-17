"""
MetaTrader 5 connector: live price data + (later) live order execution.

Requires the `MetaTrader5` Python package and a running MT5 terminal on the
SAME machine this script runs on (it talks to the terminal via local IPC,
not the internet directly) - this only works on Windows, or Wine/Linux
setups that can host an MT5 terminal.

Install: pip install MetaTrader5

I cannot run or test this connection myself (no network + no MT5 terminal
in this sandbox). Test it on your own machine with a demo account first.
"""
import pandas as pd
from datetime import datetime

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


TIMEFRAME_MAP = {
    "1min": "M1",
    "5min": "M5",
    "15min": "M15",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
}


def connect(login: int = None, password: str = None, server: str = None,
            path: str = None) -> bool:
    """
    Initialize connection to a running MT5 terminal. If login/password/
    server are omitted, connects to whichever account is already logged
    into the terminal.
    """
    if not MT5_AVAILABLE:
        raise RuntimeError(
            "MetaTrader5 package not installed. Run: pip install MetaTrader5 "
            "(Windows only, requires a running MT5 terminal)."
        )

    kwargs = {}
    if path:
        kwargs["path"] = path
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    if login and password and server:
        authorized = mt5.login(login, password=password, server=server)
        if not authorized:
            raise RuntimeError(f"MT5 login() failed: {mt5.last_error()}")

    return True


def disconnect():
    if MT5_AVAILABLE:
        mt5.shutdown()


def get_recent_bars(symbol: str, timeframe: str, n_bars: int = 500) -> pd.DataFrame:
    """
    Fetch the most recent n_bars of OHLC data for `symbol` at `timeframe`
    (one of the keys in TIMEFRAME_MAP, e.g. "1min", "4h").

    Returns a DataFrame with columns open, high, low, close and a
    DatetimeIndex, matching the format structure.py / signals.py expect.
    """
    if not MT5_AVAILABLE:
        raise RuntimeError("MetaTrader5 package not installed.")

    mt5_tf_name = TIMEFRAME_MAP.get(timeframe)
    if mt5_tf_name is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    mt5_tf = getattr(mt5, f"TIMEFRAME_{mt5_tf_name}")

    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data returned for {symbol} {timeframe}: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")
    df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
    return df[["open", "high", "low", "close"]]


def get_current_price(symbol: str):
    """Returns (bid, ask) for the symbol right now."""
    if not MT5_AVAILABLE:
        raise RuntimeError("MetaTrader5 package not installed.")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Could not get tick for {symbol}: {mt5.last_error()}")
    return tick.bid, tick.ask


def place_market_order(symbol: str, direction: int, volume: float,
                        stop_price: float, target_price: float,
                        comment: str = "pso-rimc-bot"):
    """
    Places a REAL market order. direction: 1 = buy, -1 = sell.
    Only call this once you've validated the strategy extensively in
    paper trading and demo accounts. Not used by the paper-trading bot.
    """
    if not MT5_AVAILABLE:
        raise RuntimeError("MetaTrader5 package not installed.")

    order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if direction == 1 else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": stop_price,
        "tp": target_price,
        "deviation": 10,
        "magic": 20260816,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    return result
