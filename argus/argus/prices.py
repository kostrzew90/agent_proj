import logging
from datetime import datetime, timedelta, timezone
import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

_BINANCE = "https://api.binance.com"
_GATE = "https://api.gateio.ws/api/v4/futures/usdt"
_GATE_1M_MAX_AGE = timedelta(days=6)

def _gate_spot(contract: str) -> float:
    r = httpx.get(f"{_GATE}/tickers", params={"contract": contract}, timeout=15)
    r.raise_for_status()
    return float(r.json()[0]["last"])

def _gate_historical(contract: str, when: datetime) -> float:
    start = int(when.timestamp())
    r = httpx.get(f"{_GATE}/candlesticks",
                  params={"contract": contract, "interval": "1m", "from": start, "to": start + 60},
                  timeout=15)
    r.raise_for_status()
    candles = r.json()
    if not candles:
        raise ValueError(f"no gate candle for {contract} at {when}")
    return float(candles[0]["c"])

def _binance_spot(symbol: str) -> float:
    r = httpx.get(f"{_BINANCE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=15)
    r.raise_for_status()
    return float(r.json()["price"])

def _binance_historical(symbol: str, when: datetime) -> float:
    start_ms = int(when.timestamp() * 1000)
    r = httpx.get(f"{_BINANCE}/api/v3/klines",
                  params={"symbol": symbol, "interval": "1m", "startTime": start_ms, "limit": 1},
                  timeout=15)
    r.raise_for_status()
    klines = r.json()
    if not klines:
        raise ValueError(f"no kline for {symbol} at {when}")
    return float(klines[0][4])  # close

def _yf_spot(symbol: str) -> float:
    return float(yf.Ticker(symbol).fast_info["lastPrice"])

def _yf_historical(symbol: str, when: datetime) -> float:
    hist = yf.Ticker(symbol).history(start=when.date(), period="5d")
    if hist.empty:
        raise ValueError(f"no yf history for {symbol} at {when}")
    return float(hist["Close"].iloc[0])  # najbliższy dostępny close >= when

def get_spot_price(asset) -> float:
    if asset.kind == "crypto":
        try:
            return _gate_spot(f"{asset.symbol}_USDT")
        except Exception as exc:
            logger.warning("gate spot failed for %s, falling back to binance: %s", asset.symbol, exc)
        return _binance_spot(asset.binance_symbol)
    if asset.kind == "stock":
        return _yf_spot(asset.yf_symbol)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")

def get_historical_price(asset, when: datetime) -> float:
    if asset.kind == "crypto":
        ref = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - ref <= _GATE_1M_MAX_AGE:
            try:
                return _gate_historical(f"{asset.symbol}_USDT", when)
            except Exception as exc:
                logger.warning("gate historical failed for %s, falling back to binance: %s",
                               asset.symbol, exc)
        return _binance_historical(asset.binance_symbol, when)
    if asset.kind == "stock":
        return _yf_historical(asset.yf_symbol, when)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")
