import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets
from sqlalchemy import select

from argus.db import SessionLocal
from argus.models import Asset, Liquidation
from argus.liquidations.parser import parse_force_order

logger = logging.getLogger(__name__)
_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"

def load_symbol_map(session) -> dict:
    return {a.binance_symbol.upper(): a.symbol
            for a in session.scalars(select(Asset).where(Asset.binance_symbol.isnot(None)))}

def insert_liquidations(session, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc)
    for r in rows:
        session.add(Liquidation(asset=r["asset"], exchange="binance", side=r["side"],
                                price=r["price"], qty=r["qty"], notional_usd=r["notional_usd"],
                                ts=r["ts"], raw_symbol=r["raw_symbol"], created_at=now))
    session.commit()
    return len(rows)

async def run():
    with SessionLocal() as s:
        symbol_map = load_symbol_map(s)
    logger.info("liq-listener watching %d symbols", len(symbol_map))
    backoff = 1
    fails: list[float] = []
    while True:
        connected_at = None
        try:
            async with websockets.connect(_WS_URL, ping_interval=20, ping_timeout=20) as ws:
                connected_at = time.time(); backoff = 1
                logger.info("liq-listener connected")
                async for raw in ws:
                    try:
                        rec = parse_force_order(json.loads(raw), symbol_map)
                        if rec:
                            with SessionLocal() as s:
                                insert_liquidations(s, [rec])
                    except Exception as e:
                        logger.warning("liq parse/insert error: %s", e)
        except Exception as e:
            dur = (time.time() - connected_at) if connected_at else 0
            logger.warning("liq-listener disconnected after %.0fs: %s", dur, e)
            now = time.time()
            fails = [t for t in fails if now - t < 600] + [now]
            if len(fails) >= 5:
                logger.warning("liq-listener circuit breaker: %d fails/10min -> 60s backoff", len(fails))
                await asyncio.sleep(60); fails = []
            else:
                await asyncio.sleep(backoff); backoff = min(backoff * 2, 30)

def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

if __name__ == "__main__":
    main()
