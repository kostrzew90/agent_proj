import httpx
import yfinance as yf

_BINANCE = "https://api.binance.com"

def _binance_candles(symbol: str, interval: str, limit: int) -> list[dict]:
    r = httpx.get(f"{_BINANCE}/api/v3/klines",
                  params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    return [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4])} for k in r.json()]

def _yf_candles(symbol: str, limit: int) -> list[dict]:
    hist = yf.Ticker(symbol).history(period=f"{limit}d", interval="1d")
    return [{"time": int(ts.timestamp()), "open": float(row["Open"]), "high": float(row["High"]),
             "low": float(row["Low"]), "close": float(row["Close"])}
            for ts, row in hist.iterrows()]

def get_candles(asset, interval: str | None = None, limit: int | None = None) -> list[dict]:
    if asset.kind == "crypto":
        return _binance_candles(asset.binance_symbol, interval or "1h", limit or 168)
    if asset.kind == "stock":
        return _yf_candles(asset.yf_symbol, limit or 90)
    raise ValueError(f"no price source for kind: {asset.kind}")
