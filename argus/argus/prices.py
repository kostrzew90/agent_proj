from datetime import datetime, timezone
import httpx
import yfinance as yf

_BINANCE = "https://api.binance.com"

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
        return _binance_spot(asset.binance_symbol)
    if asset.kind == "stock":
        return _yf_spot(asset.yf_symbol)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")

def get_historical_price(asset, when: datetime) -> float:
    if asset.kind == "crypto":
        return _binance_historical(asset.binance_symbol, when)
    if asset.kind == "stock":
        return _yf_historical(asset.yf_symbol, when)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")
