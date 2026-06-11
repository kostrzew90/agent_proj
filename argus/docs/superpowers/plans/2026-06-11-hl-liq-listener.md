# Hyperliquid Liquidation Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Binance WebSocket liquidation listener with a Hyperliquid `userEvents` listener that records per-asset liquidation records for tracked whale wallets.

**Architecture:** Single new file `argus/liquidations/hl_listener.py` with three layers — a pure parse function (testable without WS), a DB insert with `lid`-based dedup, and an async WS loop with reconnect + dynamic wallet re-subscription. The `liq-listener` Docker service switches entrypoint to this module; no DB migration needed.

**Tech Stack:** Python 3.12, `websockets`, SQLAlchemy (sync), `asyncio`, pytest + SQLite in-memory for tests

**Spec:** `argus/docs/superpowers/specs/2026-06-11-hl-liquidation-listener-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `argus/liquidations/hl_listener.py` | CREATE | WS listener: parse, dedup-insert, reconnect loop |
| `tests/test_hl_liq_listener.py` | CREATE | Unit tests for parse + insert; mock WS tests for reconnect + dynamic subscribe |
| `docker-compose.yml` | MODIFY | Change `liq-listener` command to `python -m argus.liquidations.hl_listener` |

**Not touched:** `argus/models.py`, `argus/db.py`, `argus/liquidations/listener.py` (kept as-is, just no longer used by the container), all API endpoints.

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

Edit files directly on VPS (or scp from local). Verify with:
```bash
docker exec argus-app-1 python -c "from argus.liquidations.hl_listener import parse_hl_liquidation; print('ok')"
```

---

## Task 1: Pure parse function + tests

**Files:**
- Create: `argus/liquidations/hl_listener.py` (parse function only)
- Create: `tests/test_hl_liq_listener.py`

`parse_hl_liquidation(event, open_positions, known_assets)` takes a raw WS message dict, a list of open position dicts, and a set of asset symbols. Returns a list of liquidation record dicts ready for DB insert. Pure function — no DB, no IO.

- [ ] **Write the failing tests**

Create `tests/test_hl_liq_listener.py`:

```python
from datetime import datetime, timezone
import pytest
from argus.liquidations.hl_listener import parse_hl_liquidation


def _event(lid=42):
    return {
        "channel": "userEvents",
        "data": {
            "user": "0xabc",
            "liquidation": {
                "lid": lid,
                "liquidator": "0xliq",
                "liquidated_user": "0xabc",
                "liquidated_ntl_pos": "50000.0",
                "liquidated_account_value": "1234.0",
            },
        },
    }


def _positions():
    return [
        {"coin": "BTC", "side": "long",  "szi": 0.5,  "entry_px": 60000.0, "position_value": 30000.0},
        {"coin": "ETH", "side": "short", "szi": -2.0, "entry_px": 3000.0,  "position_value": 6000.0},
        {"coin": "SOL", "side": "long",  "szi": 10.0, "entry_px": 150.0,   "position_value": 1500.0},
    ]


def test_parse_returns_watchlist_only():
    known = {"BTC", "ETH"}  # SOL not in watchlist
    recs = parse_hl_liquidation(_event(), _positions(), known)
    assert len(recs) == 2
    coins = {r["asset"] for r in recs}
    assert coins == {"BTC", "ETH"}


def test_parse_sides():
    known = {"BTC", "ETH"}
    recs = parse_hl_liquidation(_event(), _positions(), known)
    by_coin = {r["asset"]: r for r in recs}
    assert by_coin["BTC"]["side"] == "long_liq"
    assert by_coin["ETH"]["side"] == "short_liq"


def test_parse_fields():
    known = {"BTC"}
    recs = parse_hl_liquidation(_event(lid=99), [_positions()[0]], known)
    r = recs[0]
    assert r["exchange"] == "hyperliquid"
    assert r["price"] == 60000.0
    assert r["qty"] == 0.5
    assert r["notional_usd"] == 30000.0
    assert r["raw_symbol"] == "HL_LIQ:99"
    assert isinstance(r["ts"], datetime)


def test_parse_empty_positions():
    recs = parse_hl_liquidation(_event(), [], {"BTC"})
    assert recs == []


def test_parse_no_liquidation_key():
    event = {"channel": "userEvents", "data": {"user": "0xabc", "fills": []}}
    recs = parse_hl_liquidation(event, _positions(), {"BTC"})
    assert recs == []


def test_parse_unknown_coin_only():
    known = {"XRP"}  # none of the positions match
    recs = parse_hl_liquidation(_event(), _positions(), known)
    assert recs == []
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v 2>&1 | head -20
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
from argus.models import Asset, Liquidation, Source, WalletPosition

logger = logging.getLogger(__name__)

_HL_WS = "wss://api.hyperliquid.xyz/ws"
_RESYNC_INTERVAL = 1800  # seconds between wallet list refreshes


def parse_hl_liquidation(
    event: dict,
    open_positions: list[dict],
    known_assets: set[str],
) -> list[dict]:
    """Pure: extract per-asset liquidation records from a userEvents message.

    open_positions: list of dicts with keys coin, side, szi, entry_px, position_value
    known_assets: set of asset symbols in the watchlist
    Returns list of dicts ready for insert_hl_liquidations().
    """
    liq = (event.get("data") or {}).get("liquidation")
    if not liq:
        return []
    lid = liq.get("lid", 0)
    ts = datetime.now(timezone.utc)
    records = []
    for pos in open_positions:
        coin = pos["coin"]
        if coin not in known_assets:
            continue
        records.append({
            "asset": coin,
            "exchange": "hyperliquid",
            "side": "long_liq" if pos["side"] == "long" else "short_liq",
            "price": float(pos["entry_px"]),
            "qty": abs(float(pos["szi"])),
            "notional_usd": float(pos["position_value"]),
            "raw_symbol": f"HL_LIQ:{lid}",
            "ts": ts,
        })
    return records
```

- [ ] **Run tests — expect PASS**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

Expected: 6 tests PASS.

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener parse function + tests"
```

---

## Task 2: DB insert with lid-based dedup + tests

**Files:**
- Modify: `argus/liquidations/hl_listener.py` (add `insert_hl_liquidations`)
- Modify: `tests/test_hl_liq_listener.py` (add DB tests)

- [ ] **Write the failing DB tests**

Append to `tests/test_hl_liq_listener.py`:

```python
from argus.models import Asset, Liquidation, Source, WalletPosition
from argus.liquidations.hl_listener import insert_hl_liquidations


def _asset(session, symbol="BTC"):
    a = Asset(symbol=symbol, kind="crypto", scorable=True)
    session.add(a)
    session.commit()
    return a


def _record(lid=42, asset="BTC"):
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
    _asset(session, "BTC")
    n = insert_hl_liquidations(session, [_record(lid=1)])
    assert n == 1
    row = session.query(Liquidation).one()
    assert row.asset == "BTC"
    assert row.exchange == "hyperliquid"
    assert row.side == "long_liq"
    assert row.raw_symbol == "HL_LIQ:1"


def test_insert_dedup_same_lid(session):
    _asset(session, "BTC")
    insert_hl_liquidations(session, [_record(lid=7)])
    n = insert_hl_liquidations(session, [_record(lid=7)])  # same lid
    assert n == 0
    assert session.query(Liquidation).count() == 1


def test_insert_different_lids(session):
    _asset(session, "BTC")
    insert_hl_liquidations(session, [_record(lid=1)])
    insert_hl_liquidations(session, [_record(lid=2)])
    assert session.query(Liquidation).count() == 2


def test_wallet_positions_not_modified(session):
    """Liquidation insert must not touch wallet_positions."""
    _asset(session, "BTC")
    src = Source(handle="0xabc", kind="hyperliquid", active=True)
    session.add(src)
    session.commit()
    wp = WalletPosition(source_id=src.id, coin="BTC", side="long",
                        szi=0.5, entry_px=60000.0, position_value=30000.0,
                        opened_ts=datetime.now(timezone.utc),
                        last_seen_ts=datetime.now(timezone.utc), open=True)
    session.add(wp)
    session.commit()
    insert_hl_liquidations(session, [_record(lid=99)])
    session.refresh(wp)
    assert wp.open is True  # must be untouched
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v -k "insert or wallet_positions"
```

Expected: `ImportError: cannot import name 'insert_hl_liquidations'`

- [ ] **Add `insert_hl_liquidations` to `hl_listener.py`**

Add after `parse_hl_liquidation`:

```python
def insert_hl_liquidations(session, records: list[dict]) -> int:
    """Insert liquidation records, skipping any lid already in the table."""
    if not records:
        return 0
    # All records from one event share the same lid (same raw_symbol).
    lid_key = records[0]["raw_symbol"]
    exists = session.scalar(select(Liquidation).where(Liquidation.raw_symbol == lid_key))
    if exists:
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

- [ ] **Run tests — expect PASS**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v
```

Expected: all 10 tests PASS.

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener insert with lid dedup + tests"
```

---

## Task 3: Async WS loop (load wallets, reconnect, dynamic subscribe) + tests

**Files:**
- Modify: `argus/liquidations/hl_listener.py` (add DB helpers + `run()` + `main()`)
- Modify: `tests/test_hl_liq_listener.py` (add mock WS tests)

- [ ] **Write the failing WS tests**

Append to `tests/test_hl_liq_listener.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from argus.liquidations.hl_listener import (
    load_wallet_addresses, load_known_assets, load_open_positions
)


def test_load_wallet_addresses(session):
    session.add(Source(handle="0xaaa", kind="hyperliquid", active=True))
    session.add(Source(handle="0xbbb", kind="hyperliquid", active=True))
    session.add(Source(handle="0xccc", kind="rss", active=True))       # wrong kind
    session.add(Source(handle="0xddd", kind="hyperliquid", active=False))  # inactive
    session.commit()
    addrs = load_wallet_addresses(session)
    assert addrs == {"0xaaa", "0xbbb"}


def test_load_known_assets(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index", scorable=False))
    session.commit()
    assets = load_known_assets(session)
    assert "BTC" in assets
    assert "TOTAL" in assets  # all symbols loaded, filter is in parse


def test_load_open_positions(session):
    src = Source(handle="0xaaa", kind="hyperliquid", active=True)
    session.add(src)
    session.commit()
    session.add(WalletPosition(source_id=src.id, coin="BTC", side="long",
                               szi=1.0, entry_px=60000.0, position_value=60000.0,
                               opened_ts=datetime.now(timezone.utc),
                               last_seen_ts=datetime.now(timezone.utc), open=True))
    session.add(WalletPosition(source_id=src.id, coin="ETH", side="short",
                               szi=-2.0, entry_px=3000.0, position_value=6000.0,
                               opened_ts=datetime.now(timezone.utc),
                               last_seen_ts=datetime.now(timezone.utc), open=False))  # closed
    session.commit()
    positions = load_open_positions(session, src.id)
    assert len(positions) == 1
    assert positions[0]["coin"] == "BTC"


def test_reconnect_on_exception():
    """run() should reconnect after a WS exception with backoff."""
    connect_count = 0

    async def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count < 3:
            raise ConnectionError("forced disconnect")
        # third attempt: return a ws that immediately ends
        ws = AsyncMock()
        ws.__aenter__ = AsyncMock(return_value=ws)
        ws.__aexit__ = AsyncMock(return_value=False)
        ws.recv = AsyncMock(side_effect=asyncio.CancelledError())
        ws.send = AsyncMock()
        return ws

    async def run_briefly():
        from argus.liquidations.hl_listener import run
        try:
            await asyncio.wait_for(run(), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    with patch("argus.liquidations.hl_listener.websockets.connect", side_effect=fake_connect), \
         patch("argus.liquidations.hl_listener.SessionLocal") as mock_sl, \
         patch("argus.liquidations.hl_listener.asyncio.sleep", new_callable=AsyncMock):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.scalars.return_value = iter([])
        mock_sl.return_value = mock_session
        asyncio.run(run_briefly())

    assert connect_count >= 2  # reconnected after failure
```

- [ ] **Run tests — expect FAIL (ImportError)**

```bash
docker exec argus-app-1 pytest tests/test_hl_liq_listener.py -v -k "load_ or reconnect"
```

Expected: `ImportError: cannot import name 'load_wallet_addresses'`

- [ ] **Add DB helpers and `run()` + `main()` to `hl_listener.py`**

Append to `argus/liquidations/hl_listener.py`:

```python
def load_wallet_addresses(session) -> set[str]:
    rows = session.scalars(
        select(Source).where(Source.kind == "hyperliquid", Source.active == True)  # noqa: E712
    )
    return {s.handle for s in rows}


def load_known_assets(session) -> set[str]:
    return {a.symbol for a in session.scalars(select(Asset))}


def load_open_positions(session, source_id: int) -> list[dict]:
    rows = session.scalars(
        select(WalletPosition).where(
            WalletPosition.source_id == source_id,
            WalletPosition.open == True,  # noqa: E712
        )
    )
    return [{"coin": wp.coin, "side": wp.side, "szi": wp.szi,
             "entry_px": wp.entry_px, "position_value": wp.position_value}
            for wp in rows]


async def _handle_liquidation(event: dict, wallet_addr: str) -> None:
    with SessionLocal() as s:
        src = s.scalar(select(Source).where(Source.handle == wallet_addr))
        if src is None:
            return
        known = load_known_assets(s)
        positions = load_open_positions(s, src.id)
        records = parse_hl_liquidation(event, positions, known)
        if records:
            n = insert_hl_liquidations(s, records)
            if n:
                logger.info("hl-liq: inserted %d records for %s lid=%s",
                            n, wallet_addr[:10], records[0]["raw_symbol"])


async def run() -> None:
    backoff = 1
    fails: list[float] = []
    subscribed: set[str] = set()

    while True:
        connected_at = None
        try:
            async with websockets.connect(_HL_WS, ping_interval=20, ping_timeout=20) as ws:
                connected_at = time.time()
                backoff = 1

                # initial subscription
                with SessionLocal() as s:
                    subscribed = load_wallet_addresses(s)
                for addr in subscribed:
                    await ws.send(json.dumps(
                        {"method": "subscribe", "subscription": {"type": "userEvents", "user": addr}}
                    ))
                logger.info("hl-listener connected, watching %d wallets", len(subscribed))

                last_resync = time.time()

                async for raw in ws:
                    # periodic re-sync for new wallets
                    if time.time() - last_resync > _RESYNC_INTERVAL:
                        with SessionLocal() as s:
                            current = load_wallet_addresses(s)
                        new = current - subscribed
                        for addr in new:
                            await ws.send(json.dumps(
                                {"method": "subscribe", "subscription": {"type": "userEvents", "user": addr}}
                            ))
                            subscribed.add(addr)
                            logger.info("hl-listener subscribed new wallet %s", addr[:10])
                        last_resync = time.time()

                    try:
                        msg = json.loads(raw)
                        channel = msg.get("channel")
                        if channel == "subscriptionResponse":
                            continue
                        if channel == "userEvents" and "liquidation" in (msg.get("data") or {}):
                            addr = (msg.get("data") or {}).get("user", "")
                            await _handle_liquidation(msg, addr)
                    except Exception as e:
                        logger.warning("hl-liq parse error: %s", e)

        except Exception as e:
            dur = (time.time() - connected_at) if connected_at else 0
            logger.warning("hl-listener disconnected after %.0fs: %s", dur, e)
            now = time.time()
            fails = [t for t in fails if now - t < 600] + [now]
            if len(fails) >= 5:
                logger.warning("hl-listener circuit breaker: %d fails/10min -> 60s", len(fails))
                await asyncio.sleep(60)
                fails = []
            else:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


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

Expected: all tests PASS (the reconnect test may skip if mocking is flaky — acceptable; core parse/insert tests must all pass).

- [ ] **Verify module is importable and runnable**

```bash
docker exec argus-app-1 python -c "from argus.liquidations.hl_listener import run, parse_hl_liquidation, insert_hl_liquidations; print('ok')"
```

Expected: `ok`

- [ ] **Commit**

```bash
git add argus/liquidations/hl_listener.py tests/test_hl_liq_listener.py
git commit -m "feat(argus): hl-liq-listener WS loop, reconnect, dynamic subscribe + tests"
```

---

## Task 4: Wire docker-compose + deploy + smoke test

**Files:**
- Modify: `docker-compose.yml` (liq-listener command)

- [ ] **Update `docker-compose.yml`**

Find the `liq-listener` service section and change the `command` line:

```yaml
  liq-listener:
    build: .
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    command: ["python", "-m", "argus.liquidations.hl_listener"]
    restart: unless-stopped
```

- [ ] **Run full test suite to check no regressions**

```bash
docker exec argus-app-1 pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pre-existing tests still PASS.

- [ ] **Rebuild and restart liq-listener**

```bash
cd ~/argus
docker compose build liq-listener
docker compose up -d liq-listener
```

- [ ] **Smoke test: check logs after 15 seconds**

```bash
sleep 15 && docker logs argus-liq-listener-1 --tail 20
```

Expected output (no reconnect spam):
```
INFO:argus.liquidations.hl_listener:hl-listener connected, watching 22 wallets
```

**If you see reconnect errors instead:** run `docker exec argus-liq-listener-1 python -m argus.liquidations.hl_listener` interactively to see the real exception.

- [ ] **Verify container stays up after 2 minutes**

```bash
sleep 120 && docker ps --filter name=argus-liq-listener-1 --format "{{.Status}}"
```

Expected: `Up 2 minutes` (not restarting)

- [ ] **Commit docker-compose change**

```bash
git add docker-compose.yml
git commit -m "feat(argus): switch liq-listener to hyperliquid WS (inc 8)"
```

- [ ] **Update STATUS.md**

Append to `STATUS.md`:

```markdown
## Increment 8 — Hyperliquid Liquidation Listener (2026-06-11)

Replaced broken Binance WS listener (Oracle Cloud blocks `fstream.binance.com` WS) with Hyperliquid `userEvents` listener.

- Subscribes to `userEvents` for all 22 tracked whale wallets
- On liquidation event: reads `wallet_positions` → inserts per-asset `Liquidation` records
- Dedup by `lid` (HL liquidation ID stored in `raw_symbol` as `HL_LIQ:<lid>`)
- Dynamic re-subscription every 30 min (new wallets auto-picked up)
- Same reconnect + circuit-breaker pattern as Binance listener
- No scoring impact — market-context only (Fable review: measures direction, not leverage)
- `wallet_positions.open` NOT modified by listener (collect_wallet syncs REST truth within 15 min)
```

```bash
git add STATUS.md
git commit -m "docs(argus): STATUS increment 8 — HL liq listener"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Subscribe `userEvents` for tracked wallets → Task 3 (`load_wallet_addresses` + subscribe loop)
- ✅ On liquidation → per-asset records from `wallet_positions` → Task 3 (`_handle_liquidation`)
- ✅ Insert to `liquidations` table, no schema migration → Task 2 (`insert_hl_liquidations`)
- ✅ Dedup by `lid` → Task 2 (`raw_symbol = "HL_LIQ:<lid>"`)
- ✅ Dynamic re-subscription every 30 min → Task 3 (`_RESYNC_INTERVAL`)
- ✅ Reconnect + circuit breaker → Task 3 (`run()` backoff logic)
- ✅ DO NOT mark `wallet_positions.open=False` → confirmed in `_handle_liquidation` (no WP update)
- ✅ `exchange='hyperliquid'` → Task 2 insert
- ✅ docker-compose command change → Task 4
- ✅ Test: dedup same lid → Task 2
- ✅ Test: unknown coin skipped → Task 1 `test_parse_unknown_coin_only`
- ✅ Test: wallet_positions not modified → Task 2 `test_wallet_positions_not_modified`
- ✅ Test: reconnect → Task 3 `test_reconnect_on_exception`

**Placeholder scan:** None found.

**Type consistency:**
- `parse_hl_liquidation` defined in Task 1, imported in test Task 1 ✅
- `insert_hl_liquidations` defined in Task 2, imported in test Task 2 ✅
- `load_wallet_addresses`, `load_known_assets`, `load_open_positions` defined in Task 3, imported in test Task 3 ✅
- `_handle_liquidation` calls all three helpers and both public functions ✅
