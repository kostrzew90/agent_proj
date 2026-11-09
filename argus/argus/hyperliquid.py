import time

import httpx

_HL = "https://api.hyperliquid.xyz/info"

def fetch_positions(address: str) -> dict:
    payload = {"type": "clearinghouseState", "user": address}
    r = httpx.post(_HL, json=payload, timeout=20)
    if r.status_code == 429:
        try:
            wait = min(float(r.headers.get("Retry-After")), 10.0)
        except (TypeError, ValueError):
            wait = 2.0
        time.sleep(wait)
        r = httpx.post(_HL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    equity = float(data.get("marginSummary", {}).get("accountValue", 0) or 0)
    positions = []
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        positions.append({"coin": p["coin"], "side": "long" if szi > 0 else "short",
                          "szi": szi, "entry_px": float(p.get("entryPx") or 0),
                          "position_value": float(p.get("positionValue") or 0)})
    return {"equity": equity, "positions": positions}
