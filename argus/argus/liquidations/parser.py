from datetime import datetime, timezone

def parse_force_order(msg: dict, symbol_to_asset: dict) -> dict | None:
    o = msg.get("o") or {}
    raw = o.get("s")
    if not raw:
        return None
    asset = symbol_to_asset.get(raw.upper())
    if asset is None:
        return None
    price = float(o.get("p") or 0)
    qty = float(o.get("q") or 0)
    side = "long_liq" if o.get("S") == "SELL" else "short_liq"
    ts = datetime.fromtimestamp(int(o.get("T", 0)) / 1000, tz=timezone.utc)
    return {"asset": asset, "raw_symbol": raw, "side": side, "price": price,
            "qty": qty, "notional_usd": price * qty, "ts": ts}
