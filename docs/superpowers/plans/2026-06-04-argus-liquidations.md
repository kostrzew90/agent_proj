# Argus Increment 5 — Liquidations (market-context) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać darmowy feed zrealizowanych likwidacji (Binance futures WS) jako market-context: osobny kontener-listener → tabela `liquidations` → endpointy agregacji → panel na dashboardzie. Bez wpływu na pętlę claimów/scoringu.

**Architecture:** Nowy moduł `argus/liquidations/` (czysty `parser.py` + asyncio `listener.py`) uruchamiany jako osobna usługa compose `liq-listener` (reuse obrazu app, inny `command`). Listener czyta `!forceOrder@arr`, filtruje watchlist, pisze do `liquidations`. App udostępnia `/api/liquidations*` + panel. Prune >30 dni w dziennym jobie.

**Tech Stack:** Python 3.12, websockets, SQLAlchemy, FastAPI, pytest; frontend vanilla JS. Testy w Dockerze.

**Spec:** `docs/superpowers/specs/2026-06-04-argus-liquidations-design.md`

---

## Konwencje
- **Brak lokalnego pythona.** Testy w Dockerze (PowerShell; trusted-host przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- `parse_force_order(msg: dict, symbol_to_asset: dict) -> dict | None` → `{asset, raw_symbol, side, price, qty, notional_usd, ts}`; `side ∈ {long_liq, short_liq}`.
- Okna: `{"1h","4h","24h","7d"}`.

## Struktura plików
```
argus/argus/models.py                  # MOD — Task 1 (Liquidation)
argus/argus/liquidations/__init__.py   # NOWY — Task 2 (pusty)
argus/argus/liquidations/parser.py     # NOWY — Task 2
argus/argus/liquidations/listener.py   # NOWY — Task 3
argus/argus/liquidations/cleanup.py    # NOWY — Task 5 (prune)
argus/requirements.txt                 # MOD — Task 3 (+websockets)
argus/argus/api.py                     # MOD — Task 4 (endpointy)
argus/argus/main.py                    # MOD — Task 5 (prune w score job)
argus/docker-compose.yml               # MOD — Task 6 (liq-listener)
argus/argus/web/index.html, app.js     # MOD — Task 7
argus/tests/test_models.py             # MOD — Task 1
argus/tests/test_liq_parser.py         # NOWY — Task 2
argus/tests/test_liq_listener.py       # NOWY — Task 3
argus/tests/test_api.py                # MOD — Task 4
argus/tests/test_liq_cleanup.py        # NOWY — Task 5
```

---

### Task 1: `Liquidation` model

**Files:** Modify `argus/argus/models.py`; Modify `argus/tests/test_models.py`

- [ ] **Step 1: Append failing test to `argus/tests/test_models.py`**
```python
def test_liquidation_roundtrip(session):
    from datetime import datetime, timezone
    from argus.models import Asset, Liquidation
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    now = datetime.now(timezone.utc)
    session.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=67000.0,
                            qty=1.5, notional_usd=100500.0, ts=now, raw_symbol="BTCUSDT",
                            created_at=now))
    session.commit()
    l = session.query(Liquidation).one()
    assert l.asset == "BTC" and l.side == "long_liq" and l.notional_usd == 100500.0
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_models.py -k liquidation` → ImportError.

- [ ] **Step 3: Edit `argus/argus/models.py`**
Add `Index` to the sqlalchemy import line (currently `from sqlalchemy import (String, Float, Boolean, Integer, DateTime, ForeignKey, JSON, UniqueConstraint)` → add `, Index`). Append at end of file:
```python
class Liquidation(Base):
    __tablename__ = "liquidations"
    __table_args__ = (
        Index("idx_liquidations_asset_ts", "asset", "ts"),
        Index("idx_liquidations_ts", "ts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    exchange: Mapped[str] = mapped_column(String, default="binance")
    side: Mapped[str] = mapped_column(String)              # long_liq|short_liq
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    notional_usd: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_models.py` → all green.

- [ ] **Step 5: Commit**
```
git add argus/argus/models.py argus/tests/test_models.py
git commit -m "feat(argus): Liquidation model (+ indexes)"
```

---

### Task 2: `parse_force_order` parser

**Files:** Create `argus/argus/liquidations/__init__.py` (empty), `argus/argus/liquidations/parser.py`; Test `argus/tests/test_liq_parser.py`

- [ ] **Step 1: Write failing test `argus/tests/test_liq_parser.py`**
```python
from datetime import timezone
from argus.liquidations.parser import parse_force_order

SMAP = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

def _msg(symbol, side, p, q, t=1717500000000):
    return {"e": "forceOrder", "o": {"s": symbol, "S": side, "p": p, "q": q, "X": "FILLED", "T": t}}

def test_sell_is_long_liq_and_strings_parsed():
    r = parse_force_order(_msg("BTCUSDT", "SELL", "67000.0", "1.5"), SMAP)
    assert r["asset"] == "BTC" and r["side"] == "long_liq"
    assert r["price"] == 67000.0 and r["qty"] == 1.5
    assert r["notional_usd"] == 67000.0 * 1.5
    assert r["raw_symbol"] == "BTCUSDT"
    assert r["ts"].tzinfo == timezone.utc

def test_buy_is_short_liq():
    assert parse_force_order(_msg("ETHUSDT", "BUY", "1900", "10"), SMAP)["side"] == "short_liq"

def test_case_insensitive_symbol():
    assert parse_force_order(_msg("btcusdt", "SELL", "1", "1"), SMAP)["asset"] == "BTC"

def test_unknown_symbol_returns_none():
    assert parse_force_order(_msg("DOGEUSDT", "SELL", "1", "1"), SMAP) is None

def test_missing_o_returns_none():
    assert parse_force_order({"e": "x"}, SMAP) is None
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/liquidations/__init__.py`** (empty) and `argus/argus/liquidations/parser.py`:
```python
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
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_liq_parser.py` → `5 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/liquidations/__init__.py argus/argus/liquidations/parser.py argus/tests/test_liq_parser.py
git commit -m "feat(argus): parse_force_order liquidation parser"
```

---

### Task 3: `listener.py` (WS loop + testable helpers) + websockets dep

**Files:** Modify `argus/requirements.txt`; Create `argus/argus/liquidations/listener.py`; Test `argus/tests/test_liq_listener.py`

- [ ] **Step 1: Add dependency** — append to `argus/requirements.txt`:
```
websockets==13.*
```

- [ ] **Step 2: Write failing test `argus/tests/test_liq_listener.py`** (tests the pure helpers; the async WS loop is verified in smoke, not unit-tested)
```python
from datetime import datetime, timezone
from argus.models import Asset, Liquidation
from argus.liquidations.listener import load_symbol_map, insert_liquidations

def test_load_symbol_map_uppercased(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ethusdt", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index"))   # no binance_symbol -> excluded
    session.commit()
    m = load_symbol_map(session)
    assert m == {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

def test_insert_liquidations(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    session.commit()
    now = datetime.now(timezone.utc)
    rows = [{"asset": "BTC", "raw_symbol": "BTCUSDT", "side": "long_liq", "price": 67000.0,
             "qty": 1.0, "notional_usd": 67000.0, "ts": now}]
    n = insert_liquidations(session, rows)
    assert n == 1
    assert session.query(Liquidation).one().asset == "BTC"
```

- [ ] **Step 3: Run, verify FAIL** — ImportError (`argus.liquidations.listener`). (First run installs `websockets` into the pip cache.)

- [ ] **Step 4: Create `argus/argus/liquidations/listener.py`**
```python
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
```

- [ ] **Step 5: Run, verify PASS** — `... pytest -q tests/test_liq_listener.py` → `2 passed`.

- [ ] **Step 6: Commit**
```
git add argus/requirements.txt argus/argus/liquidations/listener.py argus/tests/test_liq_listener.py
git commit -m "feat(argus): liquidation WS listener (reconnect + circuit breaker)"
```

---

### Task 4: Endpointy `/api/liquidations` + `/api/liquidations/largest`

**Files:** Modify `argus/argus/api.py`; Test `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing tests to `argus/tests/test_api.py`**
```python
def test_liquidations_aggregate_by_window():
    from datetime import datetime, timezone, timedelta
    from argus.models import Asset, Liquidation
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    now = datetime.now(timezone.utc)
    s.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                      notional_usd=50000.0, ts=now - timedelta(minutes=30), raw_symbol="BTCUSDT", created_at=now))
    s.add(Liquidation(asset="BTC", exchange="binance", side="short_liq", price=1, qty=1,
                      notional_usd=20000.0, ts=now - timedelta(hours=3), raw_symbol="BTCUSDT", created_at=now))
    s.commit()
    one_h = client.get("/api/liquidations?window=1h").json()
    btc_1h = next(r for r in one_h if r["asset"] == "BTC")
    assert btc_1h["long_liq_usd"] == 50000.0 and btc_1h["short_liq_usd"] == 0.0   # 3h-old excluded
    day = client.get("/api/liquidations?window=24h").json()
    btc_24h = next(r for r in day if r["asset"] == "BTC")
    assert btc_24h["short_liq_usd"] == 20000.0

def test_liquidations_largest_min_notional():
    from datetime import datetime, timezone
    from argus.models import Asset, Liquidation
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    now = datetime.now(timezone.utc)
    s.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                      notional_usd=500000.0, ts=now, raw_symbol="BTCUSDT", created_at=now))
    s.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                      notional_usd=5000.0, ts=now, raw_symbol="BTCUSDT", created_at=now))
    s.commit()
    rows = client.get("/api/liquidations/largest?window=24h&min_notional=100000").json()
    assert len(rows) == 1 and rows[0]["notional_usd"] == 500000.0
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_api.py -k liquidation` → routes missing.

- [ ] **Step 3: Edit `argus/argus/api.py`**
Add to imports: `from datetime import datetime, timedelta, timezone` (if not already imported — check; add what's missing), and `Liquidation` to the models import line. (`func` and `select` already imported.) Add after the wallet routes, before the static mount:
```python
_LIQ_WINDOWS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4),
                "24h": timedelta(hours=24), "7d": timedelta(days=7)}

@app.get("/api/liquidations")
async def liquidations(window: str = "24h", session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    rows = session.execute(
        select(Liquidation.asset, Liquidation.side,
               func.sum(Liquidation.notional_usd), func.count())
        .where(Liquidation.ts >= since)
        .group_by(Liquidation.asset, Liquidation.side)).all()
    agg: dict = {}
    for asset, side, usd, n in rows:
        a = agg.setdefault(asset, {"asset": asset, "long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0})
        a["long_liq_usd" if side == "long_liq" else "short_liq_usd"] = float(usd or 0)
        a["count"] += int(n)
    return sorted(agg.values(), key=lambda r: -(r["long_liq_usd"] + r["short_liq_usd"]))

@app.get("/api/liquidations/largest")
async def liquidations_largest(window: str = "24h", min_notional: float = 100000.0,
                               session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    rows = session.scalars(
        select(Liquidation).where(Liquidation.ts >= since,
                                  Liquidation.notional_usd >= min_notional)
        .order_by(Liquidation.notional_usd.desc()).limit(50))
    return [{"asset": l.asset, "side": l.side, "notional_usd": l.notional_usd,
             "price": l.price, "ts": l.ts.isoformat()} for l in rows]
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_api.py -k liquidation` (2 passed), then WHOLE file `... pytest -q tests/test_api.py` (no regressions).

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/liquidations + /largest endpoints"
```

---

### Task 5: Prune (retencja 30 dni) + wire w score job

**Files:** Create `argus/argus/liquidations/cleanup.py`; Modify `argus/argus/main.py`; Test `argus/tests/test_liq_cleanup.py`

- [ ] **Step 1: Write failing test `argus/tests/test_liq_cleanup.py`**
```python
from datetime import datetime, timezone, timedelta
from argus.models import Asset, Liquidation
from argus.liquidations.cleanup import prune_liquidations

def test_prune_removes_old_keeps_recent(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    now = datetime.now(timezone.utc)
    session.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                            notional_usd=1, ts=now - timedelta(days=40), raw_symbol="BTCUSDT", created_at=now))
    session.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                            notional_usd=1, ts=now - timedelta(days=2), raw_symbol="BTCUSDT", created_at=now))
    session.commit()
    removed = prune_liquidations(session, days=30)
    assert removed == 1
    assert session.query(Liquidation).count() == 1
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/liquidations/cleanup.py`**
```python
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
from argus.models import Liquidation

def prune_liquidations(session, days: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = session.execute(delete(Liquidation).where(Liquidation.ts < cutoff))
    session.commit()
    return res.rowcount or 0
```

- [ ] **Step 4: Wire into `argus/argus/main.py`** — at the top add `from argus.liquidations.cleanup import prune_liquidations`. In `_score_job`, after `recompute_scores(s)`, add `prune_liquidations(s)`:
```python
def _score_job():
    with SessionLocal() as s:
        recompute_scores(s)
        prune_liquidations(s)
```

- [ ] **Step 5: Run, verify PASS + import** — `... pytest -q tests/test_liq_cleanup.py` (1 passed) and `python -c 'import argus.main; print("main ok")'` (run inside the docker invocation).

- [ ] **Step 6: Commit**
```
git add argus/argus/liquidations/cleanup.py argus/argus/main.py argus/tests/test_liq_cleanup.py
git commit -m "feat(argus): prune liquidations >30d in score job"
```

---

### Task 6: docker-compose `liq-listener` service

**Files:** Modify `argus/docker-compose.yml`

- [ ] **Step 1: Read `argus/docker-compose.yml`** to match indentation/structure.

- [ ] **Step 2: Add a `liq-listener` service** under `services:` (reuses the app image build, different command), e.g. after the `app` service:
```yaml
  liq-listener:
    build: .
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    command: ["python", "-m", "argus.liquidations.listener"]
    restart: unless-stopped
```

- [ ] **Step 3: Validate compose syntax (Docker, no app run):**
```
docker compose -f "C:\Users\DAMA\Documents\docker\n8n\argus\docker-compose.yml" config >$null; echo "compose ok"
```
Expected: `compose ok` (no YAML/schema error).

- [ ] **Step 4: Commit**
```
git add argus/docker-compose.yml
git commit -m "feat(argus): liq-listener compose service"
```

---

### Task 7: Frontend — panel „Likwidacje"

**Files:** Modify `argus/argus/web/index.html`; Modify `argus/argus/web/app.js` (manual verification)

- [ ] **Step 1: Read both web files** to append without breaking existing sections.

- [ ] **Step 2: Add to `index.html`** before `<div id="detail" ...>`:
```html
<h2>Likwidacje
  <select id="liqWin"><option>1h</option><option>4h</option><option selected>24h</option><option>7d</option></select>
</h2>
<table id="liquidations"></table>
```

- [ ] **Step 3: Append to `app.js`** and call `loadLiquidations()` at the end of `loadOverview()`, plus a listener:
```javascript
async function loadLiquidations(){
  const w = document.getElementById('liqWin').value;
  let rows = [];
  try { rows = await getJSON(`/api/liquidations?window=${w}`); } catch(e){}
  const usd = v => '$' + Math.round(v).toLocaleString();
  document.getElementById('liquidations').innerHTML =
    '<tr><th>Asset</th><th>Long liq</th><th>Short liq</th><th>#</th></tr>' + rows.map(r =>
      `<tr><td>${r.asset}</td>`+
      `<td class="bear" title="${usd(r.long_liq_usd)}">${usd(r.long_liq_usd)}</td>`+
      `<td class="bull" title="${usd(r.short_liq_usd)}">${usd(r.short_liq_usd)}</td>`+
      `<td>${r.count}</td></tr>`).join('');
}
document.getElementById('liqWin').addEventListener('change', loadLiquidations);
```
(`.bear` = red = long liquidations, `.bull` = green = short liquidations — reuse existing classes.) Add `loadLiquidations();` at the end of `loadOverview()`.

- [ ] **Step 4: Commit**
```
git add argus/argus/web/index.html argus/argus/web/app.js
git commit -m "feat(argus): dashboard liquidations panel"
```

---

### Task 8: Redeploy + smoke

**Files:** (deployment)

- [ ] **Step 1: Copy + rebuild (now builds app + liq-listener)**
```
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose up -d --build"
```

- [ ] **Step 2: Smoke (after ~30s)**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 30 && echo '--- ps ---'; cd ~/argus && docker compose ps; echo '--- listener log ---'; docker compose logs --since 2m liq-listener | tail -15; echo '--- liquidations count ---'; docker compose exec -T app python -c \"from argus.db import SessionLocal; from argus.models import Liquidation; s=SessionLocal(); print('liquidations rows:', s.query(Liquidation).count())\"; echo '--- api ---'; curl -sS 'http://localhost:8080/api/liquidations?window=1h'"
```
Expected: `liq-listener` container Up; log shows `liq-listener connected` + `watching N symbols`; after a short while `liquidations rows` > 0 (depends on live liquidation activity — may be 0 in calm markets, re-check later); `/api/liquidations` returns `[]` or aggregated rows. If rows are 0, that's acceptable if the listener connected cleanly (low market activity) — note it for re-check.

- [ ] **Step 3: Note for user** — verify via tunnel (8090): panel „Likwidacje" with window selector; data fills as liquidations occur.

---

## Self-Review

**Spec coverage:**
- Osobny kontener liq-listener (reuse obrazu) → Task 6 ✅
- parse_force_order (czysty, case-insensitive, unknown→None, stringi→float, SELL/BUY→side) → Task 2 ✅
- listener: load_symbol_map, insert, asyncio WS, reconnect+backoff+circuit breaker, ping via lib → Task 3 ✅
- Liquidation table (+ raw_symbol, created_at, indexy) → Task 1 ✅
- websockets dep → Task 3 ✅
- endpointy window 1h/4h/24h/7d + largest min_notional → Task 4 ✅
- prune 30d w score job → Task 5 ✅
- panel (czerwony long-liq / zielony short-liq, tooltip USD, selektor okna) → Task 7 ✅
- tylko watchlist (load_symbol_map z binance_symbol) → Task 3 ✅
- oddzielenie od claimów/scoringu → potwierdzone (żaden task nie tworzy claimów z likwidacji) ✅
- redeploy + smoke → Task 8 ✅

**Placeholder scan:** brak TODO/TBD; pełny kod w krokach. Task 8 deployment, Task 6 config.

**Type consistency:** `parse_force_order(msg, symbol_to_asset)->dict|None` z polami `{asset,raw_symbol,side,price,qty,notional_usd,ts}` spójny (Task 2 ↔ insert_liquidations Task 3 ↔ Liquidation model Task 1). `load_symbol_map`/`insert_liquidations`/`prune_liquidations` sygnatury zgodne (Task 3,5 ↔ testy ↔ main wiring). Okna `_LIQ_WINDOWS` (Task 4) ↔ panel select (Task 7). `side` wartości `long_liq`/`short_liq` spójne wszędzie. Importy api.py (Liquidation, timedelta) dodane w Task 4.
