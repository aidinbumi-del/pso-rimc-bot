"""
Deriv WebSocket API connector: live price data for paper trading.

Deriv (deriv.com) is available in Zimbabwe, unlike OANDA. Its API is
WebSocket-based (wss://), not REST, and its tradeable products are
multiplier/CFD contracts rather than simple "market order + stop +
target" positions like OANDA/MT5 use.

IMPORTANT: for PAPER TRADING this difference doesn't matter at all -
paper_broker.py simulates every trade itself in pure Python, it never
touches the broker's own order system. This connector only needs to
supply live price data. Going live with REAL Deriv money later would
require a different order-placement function than OANDA/MT5's
(multiplier contracts work differently) - that's flagged clearly below
and intentionally not built yet.

No API token/login is needed for the price data used here - candle and
tick history are public data on Deriv's API. A token is only required
once you build real order placement.

Install: pip install websocket-client

I cannot make live calls to Deriv myself (no network access in this
sandbox). The request-building and response-parsing logic below is
written against Deriv's documented API and unit-tested offline with
mocked responses (see test_deriv_connector.py) - the actual live
WebSocket connection is yours to confirm on first run.
"""
import json
import time
import pandas as pd

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"

# Deriv uses "frx"-prefixed symbols for forex, not "EURUSD".
SYMBOL_MAP = {
    "EURUSD": "frxEURUSD",
    "GBPUSD": "frxGBPUSD",
    "USDJPY": "frxUSDJPY",
}

GRANULARITY_SECONDS = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def parse_candles_response(data: dict) -> pd.DataFrame:
    """Pure parsing function, independent of the websocket transport,
    so it can be unit tested with hand-built response dicts."""
    candles = data.get("candles", [])
    rows = []
    for c in candles:
        rows.append((
            pd.Timestamp(c["epoch"], unit="s", tz="UTC"),
            float(c["open"]), float(c["high"]),
            float(c["low"]), float(c["close"]),
        ))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df = df.set_index("time")
    return df


def parse_tick_response(data: dict) -> float:
    """Extracts the last quote price from a ticks_history (style=ticks)
    response. Deriv's public tick feed for frx symbols gives a single
    quote, not a separate bid/ask like OANDA/MT5 - see class docstring."""
    prices = data.get("history", {}).get("prices", [])
    if not prices:
        raise RuntimeError(f"No tick data in response: {data}")
    return float(prices[-1])


class DerivConnector:
    def __init__(self, app_id: str = "1089"):
        """app_id="1089" is Deriv's published demo/testing app ID, fine
        for public price data. Register your own app_id at
        https://api.deriv.com/ for anything beyond casual testing."""
        if not WEBSOCKET_AVAILABLE:
            raise RuntimeError(
                "websocket-client package not installed. "
                "Run: pip install websocket-client"
            )
        self.app_id = app_id
        self.ws_url = DERIV_WS_URL.format(app_id=app_id)

    def _send_request(self, request: dict, timeout: int = 10) -> dict:
        """Opens a short-lived connection, sends one request, returns
        the matching response, closes. Simplest correct approach for a
        poll-every-N-seconds bot (no persistent connection state to
        manage between polls)."""
        ws = websocket.create_connection(self.ws_url, timeout=timeout)
        try:
            ws.send(json.dumps(request))
            response = json.loads(ws.recv())
            if "error" in response:
                raise RuntimeError(f"Deriv API error: {response['error']}")
            return response
        finally:
            ws.close()

    def get_recent_bars(self, symbol: str, timeframe: str,
                         n_bars: int = 500) -> pd.DataFrame:
        """symbol: plain format like "EURUSD" (mapped internally to
        Deriv's "frxEURUSD"). Returns a DataFrame with columns open,
        high, low, close and a DatetimeIndex, matching the format
        structure.py / signals.py expect."""
        deriv_symbol = SYMBOL_MAP.get(symbol, symbol)
        granularity = GRANULARITY_SECONDS.get(timeframe)
        if granularity is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        request = {
            "ticks_history": deriv_symbol,
            "style": "candles",
            "granularity": granularity,
            "count": n_bars,
            "end": "latest",
        }
        response = self._send_request(request)
        return parse_candles_response(response)

    def get_current_price(self, symbol: str):
        """Returns (price, price) - Deriv's public frx tick feed gives a
        single quote, not separate bid/ask. Treat the spread filter in
        config.py (max_spread_pips) as inactive/unreliable with this
        data source alone; it's designed for OANDA/MT5's true bid/ask."""
        deriv_symbol = SYMBOL_MAP.get(symbol, symbol)
        request = {
            "ticks_history": deriv_symbol,
            "style": "ticks",
            "count": 1,
            "end": "latest",
        }
        response = self._send_request(request)
        price = parse_tick_response(response)
        return price, price

    def get_historical_bars(self, symbol: str, timeframe: str,
                             start: pd.Timestamp, end: pd.Timestamp = None,
                             chunk_size: int = 5000) -> pd.DataFrame:
        """
        Paginates backward from `end` (default: now) fetching up to
        chunk_size candles per request via Deriv's ticks_history endpoint,
        repeating until reaching `start`. For a full year of 1-minute
        data this means dozens of requests and can take several minutes -
        this is a one-off historical-analysis tool, not something the
        live bot calls during normal operation.

        Returns a single combined, deduplicated, sorted DataFrame in the
        same format as get_recent_bars().

        I have not run this against Deriv's live servers myself (no
        network access here) - the pagination logic is verified offline
        with mocked multi-page responses (test_deriv_connector.py), but
        real-world behavior (rate limits, exact per-request caps, how
        far back history actually goes for this symbol) is yours to
        confirm on first run.
        """
        deriv_symbol = SYMBOL_MAP.get(symbol, symbol)
        granularity = GRANULARITY_SECONDS.get(timeframe)
        if granularity is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        if end is None:
            end = pd.Timestamp.now(tz="UTC")

        end_epoch = int(end.timestamp())
        start_epoch = int(start.timestamp())

        all_frames = []
        current_end = end_epoch
        seen_earliest = None

        while current_end > start_epoch:
            request = {
                "ticks_history": deriv_symbol,
                "style": "candles",
                "granularity": granularity,
                "count": chunk_size,
                "end": current_end,
            }
            response = self._send_request(request)
            chunk = parse_candles_response(response)
            if chunk.empty:
                break
            all_frames.append(chunk)
            earliest_ts = chunk.index.min()
            if seen_earliest is not None and earliest_ts >= seen_earliest:
                # Not making progress (e.g. hit the start of available
                # history) - stop rather than loop forever.
                break
            seen_earliest = earliest_ts
            current_end = int(earliest_ts.timestamp()) - granularity
            time.sleep(0.3)  # be polite to the API between requests

        if not all_frames:
            return pd.DataFrame(columns=["open", "high", "low", "close"])

        combined = pd.concat(all_frames)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined = combined.sort_index()
        combined = combined[(combined.index >= start) & (combined.index <= end)]
        return combined
