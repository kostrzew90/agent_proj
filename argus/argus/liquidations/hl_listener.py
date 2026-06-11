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


def _load_wallets(session) -> set[str]:
    return {s.handle for s in session.scalars(
        select(Source).where(Source.kind == "hyperliquid", Source.active == True)  # noqa: E712
    )}


def _load_known_assets(session) -> set[str]:
    return {a.symbol for a in session.scalars(select(Asset))}


async def _wallet_task(addr: str, known_assets: frozenset[str]) -> None:
    backoff = 1
    fails: list[float] = []

    while True:
        connected_at = None
        try:
            async with websockets.connect(_HL_WS, ping_interval=20, ping_timeout=20) as ws:
                connected_at = time.time()
                backoff = 1
                await ws.send(json.dumps(
                    {"method": "subscribe", "subscription": {"type": "userEvents", "user": addr}}
                ))
                logger.info("hl-liq [%s]: connected", addr[:10])

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("channel") != "userEvents":
                            continue
                        records = parse_hl_liquidation(msg, known_assets)
                        if records:
                            with SessionLocal() as s:
                                n = insert_hl_liquidations(s, records)
                            if n:
                                logger.info("hl-liq [%s]: inserted %d liq records (lid=%s)",
                                            addr[:10], n, records[0]["raw_symbol"])
                    except Exception as e:
                        logger.warning("hl-liq [%s]: parse/insert error: %s", addr[:10], e)

        except asyncio.CancelledError:
            logger.info("hl-liq [%s]: task cancelled", addr[:10])
            return
        except Exception as e:
            dur = (time.time() - connected_at) if connected_at else 0
            logger.warning("hl-liq [%s]: disconnected after %.0fs: %s", addr[:10], dur, e)
            now = time.time()
            fails = [t for t in fails if now - t < _CIRCUIT_BREAKER_WINDOW] + [now]
            if len(fails) >= _CIRCUIT_BREAKER_LIMIT:
                logger.warning("hl-liq [%s]: circuit breaker -> %ds", addr[:10], _CIRCUIT_BREAKER_SLEEP)
                await asyncio.sleep(_CIRCUIT_BREAKER_SLEEP)
                fails = []
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)


async def run() -> None:
    with SessionLocal() as s:
        wallets = _load_wallets(s)
        known_assets = frozenset(_load_known_assets(s))

    tasks: dict[str, asyncio.Task] = {}
    for addr in wallets:
        tasks[addr] = asyncio.create_task(_wallet_task(addr, known_assets))
    logger.info("hl-listener: started %d wallet tasks", len(tasks))

    while True:
        await asyncio.sleep(_MANAGER_INTERVAL)
        with SessionLocal() as s:
            current = _load_wallets(s)
            known_assets = frozenset(_load_known_assets(s))
        new = current - set(tasks)
        for addr in new:
            tasks[addr] = asyncio.create_task(_wallet_task(addr, known_assets))
            logger.info("hl-listener: spawned task for new wallet %s", addr[:10])
        for addr in list(tasks):
            if tasks[addr].done():
                logger.warning("hl-liq [%s]: task exited unexpectedly, restarting", addr[:10])
                tasks[addr] = asyncio.create_task(_wallet_task(addr, known_assets))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
