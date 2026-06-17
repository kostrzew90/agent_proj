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
_MAX_USERS_PER_CONN = 15   # HL hard limit: "Cannot track more than 15 total users"
_MANAGER_INTERVAL = 300
_MAX_BACKOFF = 60
_CIRCUIT_BREAKER_LIMIT = 5
_CIRCUIT_BREAKER_WINDOW = 600
_CIRCUIT_BREAKER_SLEEP = 300


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


def _load_wallets(session) -> list[str]:
    return [s.handle for s in session.scalars(
        select(Source).where(Source.kind == "hyperliquid", Source.active == True)  # noqa: E712
    )]


def _load_known_assets(session) -> set[str]:
    return {a.symbol for a in session.scalars(select(Asset))}


async def _subscribe(ws, addr: str) -> None:
    await ws.send(json.dumps(
        {"method": "subscribe", "subscription": {"type": "userEvents", "user": addr}}
    ))


async def _ping_loop(ws) -> None:
    while True:
        await asyncio.sleep(30)
        await ws.send(json.dumps({"method": "ping"}))


async def _receive_loop(ws, known_assets: frozenset[str]) -> None:
    async for raw in ws:
        try:
            msg = json.loads(raw)
            ch = msg.get("channel", "?")
            # Log any non-routine channel so we can confirm real event channel name
            if ch not in ("pong", "subscriptionResponse", "user"):
                logger.info("hl-diag ch=%r raw=%s", ch, raw[:400])
            if ch != "user":
                continue
            records = parse_hl_liquidation(msg, known_assets)
            if records:
                with SessionLocal() as s:
                    n = insert_hl_liquidations(s, records)
                if n:
                    logger.info("hl-listener: inserted %d liq records", n)
        except Exception as e:
            logger.warning("hl-listener: parse/insert error: %s", e)


async def _refresh_loop(ws, subscribed: set[str]) -> None:
    while True:
        await asyncio.sleep(_MANAGER_INTERVAL)
        with SessionLocal() as s:
            current = set(_load_wallets(s))
        for addr in current - subscribed:
            if len(subscribed) >= _MAX_USERS_PER_CONN:
                break
            await _subscribe(ws, addr)
            subscribed.add(addr)
            logger.info("hl-listener: subscribed new wallet %s", addr[:10])


async def _run_connection(wallets: list[str], known_assets: frozenset[str]) -> None:
    async with websockets.connect(_HL_WS, ping_interval=None, ping_timeout=None) as ws:
        subscribed: set[str] = set()
        for addr in wallets:
            await _subscribe(ws, addr)
            subscribed.add(addr)
        logger.info("hl-listener: connected, subscribed %d wallets", len(subscribed))

        receive = asyncio.create_task(_receive_loop(ws, known_assets))
        refresh = asyncio.create_task(_refresh_loop(ws, subscribed))
        ping = asyncio.create_task(_ping_loop(ws))
        done, pending = await asyncio.wait({receive, refresh, ping}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        for t in done:
            if exc := t.exception():
                raise exc


async def _run_chunk_loop(chunk: list[str], known_assets: frozenset[str]) -> None:
    backoff = 1
    fails: list[float] = []
    label = chunk[0][:10] if chunk else "?"

    while True:
        try:
            await _run_connection(chunk, known_assets)
        except asyncio.CancelledError:
            logger.info("hl-listener: chunk %s cancelled", label)
            return
        except Exception as e:
            logger.warning("hl-listener: chunk %s connection lost: %s", label, e)
            now = time.time()
            fails = [t for t in fails if now - t < _CIRCUIT_BREAKER_WINDOW] + [now]
            if len(fails) >= _CIRCUIT_BREAKER_LIMIT:
                logger.warning("hl-listener: chunk %s circuit breaker -> %ds", label, _CIRCUIT_BREAKER_SLEEP)
                await asyncio.sleep(_CIRCUIT_BREAKER_SLEEP)
                fails = []
                backoff = 1
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)


async def run() -> None:
    with SessionLocal() as s:
        wallets = _load_wallets(s)
        known_assets = frozenset(_load_known_assets(s))

    if not wallets:
        logger.warning("hl-listener: no wallets configured, exiting")
        return

    chunks = [wallets[i:i + _MAX_USERS_PER_CONN] for i in range(0, len(wallets), _MAX_USERS_PER_CONN)]
    logger.info("hl-listener: %d wallets → %d connections", len(wallets), len(chunks))
    await asyncio.gather(*[_run_chunk_loop(chunk, known_assets) for chunk in chunks])


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
