# Hyperliquid Liquidation Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Binance WebSocket liquidation listener with a Hyperliquid `userEvents` listener that records per-asset liquidation records for tracked whale wallets.

**Architecture:** One `asyncio.Task` per wallet, each with its own WS connection to `wss://api.hyperliquid.xyz/ws`. Liquidations arrive as fills with `liquidationId` field inside `data.fills`. A background manager task polls the DB every 5 min and spawns new tasks for newly-added wallets. No DB reads during event handling — all liquidation data comes from the fill payload itself (exact price, qty, coin, timestamp). `wallet_positions` is never touched by the listener.

**Tech Stack:** Python 3.12, `websockets`, SQLAlchemy (sync), `asyncio`, pytest + SQLite in-memory

**Spec:** `argus/docs/superpowers/specs/2026-06-11-hl-liquidation-listener-design.md`

**Key findings verified before writing this plan:**
- `wss://api.hyperliquid.xyz/ws` connects fine from Oracle Cloud VPS ✅
- `userEvents` payload has **no `data.user` field** (confirmed by official SDK TODO comment) → cannot multiplex wallets on one connection
- Liquidations arrive as **fills with `liquidationId`** inside `data.fills`, not a separate `liquidation` key
- `userFills` subscription **does** have `data.user` but liquidation structure same; `userEvents` chosen for broader event coverage per spec
- 22 concurrent WS connections is trivial for asyncio (Fable: "each costs ~KB memory, HL allows ~100/IP")

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `argus/liquidations/hl_listener.py` | CREATE | Parse fills, dedup insert, per-wallet task, wallet manager |
| `tests/test_hl_liq_listener.py` | CREATE | Unit tests for parse + insert; asyncio tests for reconnect + dynamic spawn |
| `docker-compose.yml` | MODIFY | Change `liq-listener` command to `python -m argus.liquidations.hl_listener` |

**Not touched:** `argus/models.py`, `argus/db.py`, `argus/liquidations/listener.py` (kept, just unused), all API endpoints, `wallet_positions` table.

---

## Working environment

All commands run **on the VPS** via SSH:
```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129
cd ~/argus
```

Run tests inside the app container:
```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

---

## Task 1: Parse function + tests

**Files:**
- Create: `argus/liquidations/hl_listener.py` (parse function only)
- Create: `tests/test_hl_liq_listener.py`

`parse_hl_liquidation(event, known_assets)` takes a raw WS message dict and a set of known asset symbols. Returns a list of liquidation record dicts. Pure function — no DB, no IO. Liquidation data comes entirely from the fill payload: exact price, qty, coin, timestamp. No `wallet_positions` lookup needed.

Liquidation fill detection: `fill.get("liquidationId") is not None`.

Side detection: `fill["dir"]` contains `"Long"` → `long_liq`, otherwise `short_liq`.

- [ ] **Write the failing tests**

Create `tests/test_hl_liq_listener.py`:

```python
from datetime import datetime, timezone
import pytest
from argus.liquidations.hl_listener import parse_hl_liquidation


def _event(lid=42, coin="BTC", side_dir="Liquidated Long", px="60000", sz="0.5", ts_ms=1700000000000):
    return {
        "channel": "userEvents",
        "data": {
            "fills": [
                {
                    "coin": coin,
                    "px": px,
                    "sz": sz,
                    "side": "A",
                    "time": ts_ms,
                    "dir": side_dir,
                    "closedPnl": "-1000.0",
                    "liquidationId": lid,
                    "hash": "0xabc",
                    "oid": 123,
                    "crossed": True,
                    "fee": "1.5",
                    "tid": 456,
                    "feeToken": "USDC",
                }
            ]
        },
    }


def _non_liq_event():
    return {
        "channel": "userEvents",
        "data": {
            "fills": [
                {
                    "coin": "BTC",
                    "px": "61000",
                    "sz": "0.1",
                    "side": "B",
                    "time": 1700000000000,
                    "dir": "Open Long",
                    "closedPnl": "0",
                    "liquidationId": None,
                    "hash": "0xdef",
                    "oid": 789,
                    "crossed": False,
                    "fee": "0.5",
                    "tid": 111,
                    "feeToken": "USDC",
                }
            ]
        },
    }


def test_parse_returns_liquidation_fill():
    recs = parse_hl_liquidation(_event(), {"BTC"})
    assert len(recs) == 1
    r = recs[0]
    assert r["asset"] == "BTC"
    assert r["exchange"] == "hyperliquid"
    assert r["side"] == "long_liq"
    assert r["price"] == 60000.0
    assert r["qty"] == 0.5
    assert r["notional_usd"] == pytest.approx(30000.0)
    assert r["raw_symbol"] == "HL_LIQ:42"
    assert isinstance(r["ts"], datetime)
    assert r["ts"].tzinfo is not None


def test_parse_short_liquidation():
    recs = parse_hl_liquidation(_event(side_dir="Liquidated Short"), {"BTC"})
    assert recs[0]["side"] == "short_liq"


def test_parse_skips_non_liquidation_fill():
    recs = parse_hl_liquidation(_non_liq_event(), {"BTC"})
    assert recs == []


def test_parse_skips_unknown_coin():
    recs = parse_hl_liquidation(_event(coin="SOL"), {"BTC", "ETH"})
    assert recs == []


def test_parse_empty_fills():
    event = {"channel": "userEvents", "data": {"fills": []}}
    recs = parse_hl_liquidation(event, {"BTC"})
    assert recs == []


def test_parse_no_fills_key():
    event = {"channel": "userEvents", "data": {}}
    recs = parse_hl_liquidation(event, {"BTC"})
    assert recs == []


def test_parse_mixed_fills():
    """One liq fill + one normal fill in same event → only liq returned."""
    event = {
        "channel": "userEvents",
        "data": {
            "fills": [
                _event(lid=1)["data"]["fills"][0],
                _non_liq_event()["data"]["fills"][0],
            ]
        },
    }
    recs = parse_hl_liquidation(event, {"BTC"})
    assert len(recs) == 1
    assert recs[0]["raw_symbol"] == "HL_LIQ:1"
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'parse_hl_liquidation'`

- [ ] **Create `argus/liquidations/hl_listener.py` with parse function**

```python
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
_MANAGER_INTERVAL = 300   # seconds between wallet list polls
_MAX_BACKOFF = 30
_CIRCUIT_BREAKER_WINDOW = 600
_CIRCUIT_BREAKER_LIMIT = 5
_CIRCUIT_BREAKER_SLEEP = 60


def parse_hl_liquidation(event: dict, known_assets: set[str]) -> list[dict]:
    """Pure: extract liquidation records from a userEvents fill message.

    Liquidation fills have liquidationId != None.
    Side is inferred from dir field: contains 'Long' -> long_liq, else short_liq.
    Returns list of dicts ready for insert_hl_liquidations().
    """
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
```

- [ ] **Run tests — expect PASS**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

Expected: 7 tests PASS.

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener parse function + tests"
```

---

## Task 2: DB insert with lid dedup + tests

**Files:**
- Modify: `argus/liquidations/hl_listener.py` (add `insert_hl_liquidations`)
- Modify: `tests/test_hl_liq_listener.py` (add DB tests)

Dedup: check if any row with `raw_symbol == "HL_LIQ:{lid}"` exists before inserting. All fills in one event share the same `lid` → one dedup check covers the batch.

- [ ] **Write the failing DB tests**

Append to `tests/test_hl_liq_listener.py`:

```python
from datetime import datetime, timezone
from argus.models import Asset, Liquidation, Source, WalletPosition
from argus.liquidations.hl_listener import insert_hl_liquidations


def _btc(session):
    a = Asset(symbol="BTC", kind="crypto", scorable=True)
    session.add(a)
    session.commit()
    return a


def _rec(lid=1, asset="BTC"):
    return {
        "asset": asset,
        "exchange": "hyperliquid",
        "side": "long_liq",
        "price": 60000.0,
        "qty": 0.5,
        "notional_usd": 30000.0,
        "raw_symbol": f"HL_LIQ:{lid}",
        "ts": datetime.now(timezone.utc),
    }


def test_insert_basic(session):
    _btc(session)
    n = insert_hl_liquidations(session, [_rec(lid=1)])
    assert n == 1
    row = session.query(Liquidation).one()
    assert row.asset == "BTC"
    assert row.exchange == "hyperliquid"
    assert row.side == "long_liq"
    assert row.raw_symbol == "HL_LIQ:1"
    assert row.created_at is not None


def test_insert_dedup_same_lid(session):
    _btc(session)
    insert_hl_liquidations(session, [_rec(lid=7)])
    n = insert_hl_liquidations(session, [_rec(lid=7)])
    assert n == 0
    assert session.query(Liquidation).count() == 1


def test_insert_different_lids(session):
    _btc(session)
    insert_hl_liquidations(session, [_rec(lid=1)])
    insert_hl_liquidations(session, [_rec(lid=2)])
    assert session.query(Liquidation).count() == 2


def test_insert_empty(session):
    n = insert_hl_liquidations(session, [])
    assert n == 0


def test_wallet_positions_not_modified(session):
    """insert_hl_liquidations must not touch wallet_positions."""
    _btc(session)
    src = Source(handle="0xabc", kind="hyperliquid", active=True)
    session.add(src)
    session.commit()
    wp = WalletPosition(
        source_id=src.id, coin="BTC", side="long",
        szi=0.5, entry_px=60000.0, position_value=30000.0,
        opened_ts=datetime.now(timezone.utc),
        last_seen_ts=datetime.now(timezone.utc), open=True,
    )
    session.add(wp)
    session.commit()
    insert_hl_liquidations(session, [_rec(lid=99)])
    session.refresh(wp)
    assert wp.open is True
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v -k "insert or wallet_pos" 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'insert_hl_liquidations'`

- [ ] **Add `insert_hl_liquidations` to `hl_listener.py`**

Append after `parse_hl_liquidation`:

```python
def insert_hl_liquidations(session, records: list[dict]) -> int:
    """Insert liquidation records; skip entire batch if lid already present."""
    if not records:
        return 0
    lid_key = records[0]["raw_symbol"]  # all records share same lid
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
```

- [ ] **Run all tests — expect PASS**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

Expected: 12 tests PASS.

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener insert with lid dedup + tests"
```

---

## Task 3: Per-wallet WS task + wallet manager + tests

**Files:**
- Modify: `argus/liquidations/hl_listener.py` (add `_wallet_task`, `_load_wallets`, `_load_known_assets`, `run`, `main`)
- Modify: `tests/test_hl_liq_listener.py` (add async tests)

`_wallet_task(addr)` — async loop for one wallet: connect, subscribe `userEvents`, receive fills, parse + insert liquidations, reconnect with backoff on disconnect.

`run()` — loads wallets from DB, starts one `_wallet_task` per wallet via `asyncio.create_task`, then polls DB every `_MANAGER_INTERVAL` seconds for new wallets and spawns tasks for them.

- [ ] **Write the failing async tests**

Append to `tests/test_hl_liq_listener.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from argus.liquidations.hl_listener import _load_wallets, _load_known_assets


def test_load_wallets(session):
    session.add(Source(handle="0xaaa", kind="hyperliquid", active=True))
    session.add(Source(handle="0xbbb", kind="hyperliquid", active=True))
    session.add(Source(handle="0xccc", kind="rss", active=True))
    session.add(Source(handle="0xddd", kind="hyperliquid", active=False))
    session.commit()
    addrs = _load_wallets(session)
    assert addrs == {"0xaaa", "0xbbb"}


def test_load_known_assets(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index", scorable=False))
    session.commit()
    assets = _load_known_assets(session)
    assert "BTC" in assets
    assert "TOTAL" in assets


def test_wallet_task_reconnects():
    """_wallet_task should reconnect after a WS exception."""
    connect_count = 0

    async def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            raise ConnectionError("forced")
        ws = AsyncMock()
        ws.__aenter__ = AsyncMock(return_value=ws)
        ws.__aexit__ = AsyncMock(return_value=False)
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=asyncio.CancelledError())
        return ws

    async def run_task():
        from argus.liquidations.hl_listener import _wallet_task
        try:
            await asyncio.wait_for(
                _wallet_task("0xabc", frozenset({"BTC"})),
                timeout=0.3,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    with patch("argus.liquidations.hl_listener.websockets.connect", side_effect=fake_connect), \
         patch("argus.liquidations.hl_listener.SessionLocal") as mock_sl, \
         patch("argus.liquidations.hl_listener.asyncio.sleep", new_callable=AsyncMock):
        mock_s = MagicMock()
        mock_s.__enter__ = MagicMock(return_value=mock_s)
        mock_s.__exit__ = MagicMock(return_value=False)
        mock_s.scalar.return_value = None
        mock_sl.return_value = mock_s
        asyncio.run(run_task())

    assert connect_count >= 2
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v -k "load_ or reconnect" 2>&1 | head -10
```

Expected: `ImportError: cannot import name '_load_wallets'`

- [ ] **Add `_load_wallets`, `_load_known_assets`, `_wallet_task`, `run`, `main` to `hl_listener.py`**

Append to `argus/liquidations/hl_listener.py`:

```python
def _load_wallets(session) -> set[str]:
    return {s.handle for s in session.scalars(
        select(Source).where(Source.kind == "hyperliquid", Source.active == True)  # noqa: E712
    )}


def _load_known_assets(session) -> set[str]:
    return {a.symbol for a in session.scalars(select(Asset))}


async def _wallet_task(addr: str, known_assets: frozenset[str]) -> None:
    """Persistent WS loop for one wallet. Reconnects with exponential backoff."""
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
    """Start per-wallet tasks; poll for new wallets every _MANAGER_INTERVAL seconds."""
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
        # clean up finished tasks (shouldn't happen, but defensive)
        for addr in list(tasks):
            if tasks[addr].done():
                logger.warning("hl-liq [%s]: task exited unexpectedly, restarting", addr[:10])
                tasks[addr] = asyncio.create_task(_wallet_task(addr, known_assets))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Run all tests — expect PASS**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

Expected: 15 tests PASS.

- [ ] **Verify module is importable and entrypoint works**

```bash
docker exec argus-app-1 python -c "from argus.liquidations.hl_listener import run, parse_hl_liquidation, insert_hl_liquidations, _wallet_task; print('ok')"
```

Expected: `ok`

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener per-wallet tasks, manager, reconnect + tests"
```

---

## Task 4: Wire docker-compose + deploy + smoke test

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Update `docker-compose.yml` liq-listener command**

Find the `liq-listener` service and change `command`:

```yaml
  liq-listener:
    build: .
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    command: ["python", "-m", "argus.liquidations.hl_listener"]
    restart: unless-stopped
```

- [ ] **Run full test suite — check no regressions**

```bash
docker exec argus-app-1 pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: all pre-existing tests PASS, new tests PASS.

- [ ] **Rebuild and restart liq-listener**

```bash
cd ~/argus
docker compose build liq-listener
docker compose up -d liq-listener
```

- [ ] **Smoke test — check logs after 20 seconds**

```bash
sleep 20 && docker logs argus-liq-listener-1 --tail 30
```

Expected (one line per wallet, no reconnect spam):
```
INFO:argus.liquidations.hl_listener:hl-listener: started 22 wallet tasks
INFO:argus.liquidations.hl_listener:hl-liq [0x5078c2fb]: connected
INFO:argus.liquidations.hl_listener:hl-liq [0x5b5d5120]: connected
...
```

**If you see repeated disconnect/reconnect:** run interactively to see the real error:
```bash
docker exec argus-liq-listener-1 python -m argus.liquidations.hl_listener
```

- [ ] **Verify container stays up after 2 minutes**

```bash
sleep 120 && docker ps --filter name=argus-liq-listener-1 --format "{{.Status}}"
```

Expected: `Up 2 minutes` (not restarting)

- [ ] **Commit docker-compose + STATUS**

Append to `STATUS.md`:

```markdown
## Increment 8 — Hyperliquid Liquidation Listener (2026-06-11)

Replaced broken Binance WS listener (Oracle Cloud blocks `fstream.binance.com` WS).

**Architecture:** one `asyncio.Task` per tracked whale wallet, each with its own WS connection. Background manager polls DB every 5 min and spawns tasks for new wallets (added by HyperStats job).

**Key design decisions:**
- Liquidations detected from `data.fills` where `fill.liquidationId != None` (not a separate `liquidation` key)
- Exact liquidation price and timestamp from fill payload (better than entry_px from wallet_positions)
- Dedup by `raw_symbol = "HL_LIQ:{liquidationId}"` — safe across reconnects
- `wallet_positions` NOT touched (collect_wallet syncs REST truth within 15 min — Fable review)
- No scoring impact — market-context only (Fable review: measures direction, not leverage)
- Single-socket multiplexing NOT used: HL `userEvents` has no `data.user` field (confirmed by official SDK TODO)
```

```bash
git add docker-compose.yml STATUS.md
git commit -m "feat(argus): deploy hl-liq-listener + STATUS inc 8"
```

---

## Self-Review

**Spec coverage:**
- ✅ Subscribe `userEvents` per wallet → `_wallet_task` subscribes on connect
- ✅ Liquidation detection → `parse_hl_liquidation` checks `liquidationId != None`
- ✅ Insert to `liquidations` table, no schema migration → `insert_hl_liquidations`
- ✅ Dedup by `lid` → `raw_symbol = "HL_LIQ:{lid}"`
- ✅ Dynamic subscription for new wallets → manager loop + `asyncio.create_task`
- ✅ Reconnect + circuit breaker → `_wallet_task` backoff logic
- ✅ `wallet_positions` NOT touched → no WP updates anywhere
- ✅ `exchange='hyperliquid'` → set explicitly in `insert_hl_liquidations`
- ✅ docker-compose command change → Task 4

**Opus fixes applied:**
- ✅ No `data.user` multiplexing bug → per-wallet tasks (one connection each)
- ✅ No resync starvation → manager is a separate `asyncio.sleep` loop, independent of message arrival
- ✅ `exchange` set explicitly, not relying on model default `"binance"`
- ✅ Dedup via SELECT before INSERT (no unique index needed for single-process listener)

**Placeholder scan:** None found — all steps have exact code.

**Type consistency:**
- `parse_hl_liquidation(event, known_assets)` — defined Task 1, used Task 3 ✅
- `insert_hl_liquidations(session, records)` — defined Task 2, used Task 3 ✅
- `_load_wallets(session)` / `_load_known_assets(session)` — defined Task 3, tested Task 3 ✅
- `_wallet_task(addr, known_assets)` takes `frozenset[str]` — consistent across Task 3 ✅
