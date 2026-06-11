import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets
from sqlalchemy import select

from argus.db import SessionLocal
from argus.models import Asset, Liquidation, Source

logger = logging.getLogger(__name__)

_HL_WS = "wss://api.hyperliquid.xyz/ws"
_MANAGER_INTERVAL = 300
_MAX_BACKOFF = 30
_CIRCUIT_BREAKER_WINDOW = 600
_CIRCUIT_BREAKER_LIMIT = 5
_CIRCUIT_BREAKER_SLEEP = 60


def parse_hl_liquidation(event: dict, known_assets: set[str]) -> list[dict]:
    fills = (event.get("data") or {}).get("fills") or []
    records = []
    for fill in fills:
        lid = fill.get("liquidationId")
        if lid is None:
            continue
        coin = fill.get("coin", "")
        if coin not in known_assets:
            continue
        direction = fill.get("dir", "")
        price = float(fill.get("px", 0))
        qty = abs(float(fill.get("sz", 0)))
        ts_ms = fill.get("time", 0)
        records.append({
            "asset": coin,
            "exchange": "hyperliquid",
            "side": "long_liq" if "Long" in direction else "short_liq",
            "price": price,
            "qty": qty,
            "notional_usd": price * qty,
            "raw_symbol": f"HL_LIQ:{lid}",
            "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
        })
    return records



def insert_hl_liquidations(session, records: list[dict]) -> int:
    if not records:
        return 0
    lid_key = records[0]["raw_symbol"]
    if session.scalar(select(Liquidation).where(Liquidation.raw_symbol == lid_key)):
        return 0
    now = datetime.now(timezone.utc)
    for r in records:
        session.add(Liquidation(
            asset=r["asset"],
            exchange=r["exchange"],
            side=r["side"],
            price=r["price"],
            qty=r["qty"],
            notional_usd=r["notional_usd"],
            ts=r["ts"],
            raw_symbol=r["raw_symbol"],
            created_at=now,
        ))
    session.commit()
    return len(records)
