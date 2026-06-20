import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from argus.db import SessionLocal
from argus.models import Asset, Liquidation, Source

logger = logging.getLogger(__name__)

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"
_POLL_INTERVAL = int(os.environ.get("HL_POLL_INTERVAL", "120"))
_CONCURRENCY = 1   # sequential — HL rate-limits at ~0.5 req/s
_REQUEST_DELAY = 2.0  # 0.5 req/s → 43 wallets ≈ 90s per cycle
_REQUEST_TIMEOUT = 20


def parse_hl_liquidation(fills: list[dict], known_assets: set[str]) -> list[dict]:
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
    raw_symbols = [r["raw_symbol"] for r in records]
    existing = set(session.scalars(
        select(Liquidation.raw_symbol).where(Liquidation.raw_symbol.in_(raw_symbols))
    ))
    new_records = [r for r in records if r["raw_symbol"] not in existing]
    if not new_records:
        return 0
    now = datetime.now(timezone.utc)
    for r in new_records:
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
    return len(new_records)


def _load_wallets(session) -> list[str]:
    return [s.handle for s in session.scalars(
        select(Source).where(Source.kind == "hyperliquid", Source.active == True)  # noqa: E712
    )]


def _load_known_assets(session) -> set[str]:
    return {a.symbol for a in session.scalars(select(Asset))}


async def _fetch_fills(client: httpx.AsyncClient, addr: str) -> list[dict]:
    resp = await client.post(
        _HL_INFO_URL,
        json={"type": "userFills", "user": addr},
        timeout=_REQUEST_TIMEOUT,
    )
    if resp.status_code == 429:
        retry_after = float(resp.headers.get("Retry-After", "3"))
        await asyncio.sleep(min(retry_after, 10))
        resp = await client.post(
            _HL_INFO_URL,
            json={"type": "userFills", "user": addr},
            timeout=_REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()


async def _poll_wallet(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    addr: str,
    known_assets: frozenset[str],
) -> int:
    async with sem:
        await asyncio.sleep(_REQUEST_DELAY)
        fills = await _fetch_fills(client, addr)
    records = parse_hl_liquidation(fills, known_assets)
    if not records:
        return 0
    with SessionLocal() as s:
        return insert_hl_liquidations(s, records)


async def _poll_all(wallets: list[str], known_assets: frozenset[str]) -> int:
    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_poll_wallet(client, sem, addr, known_assets) for addr in wallets],
            return_exceptions=True,
        )
    total = 0
    for addr, r in zip(wallets, results):
        if isinstance(r, Exception):
            logger.warning("hl-poll: error wallet %s: %s", addr[:10], r)
        else:
            total += r
    return total


async def run() -> None:
    logger.info("hl-poll: starting REST polling, interval=%ds", _POLL_INTERVAL)
    while True:
        try:
            with SessionLocal() as s:
                wallets = _load_wallets(s)
                known_assets = frozenset(_load_known_assets(s))
            if not wallets:
                logger.warning("hl-poll: no wallets configured, exiting")
                return
            t0 = time.monotonic()
            n = await _poll_all(wallets, known_assets)
            elapsed = time.monotonic() - t0
            logger.info(
                "hl-poll: polled %d wallets in %.1fs, inserted %d liq records",
                len(wallets), elapsed, n,
            )
        except Exception as e:
            logger.error("hl-poll: unexpected error: %s", e)
        await asyncio.sleep(_POLL_INTERVAL)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
