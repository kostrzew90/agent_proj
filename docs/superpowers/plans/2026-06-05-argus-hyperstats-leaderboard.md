# Argus Increment 7 — HyperStats Leaderboard Auto-Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-odkrywać dobrych traderów Hyperliquid z darmowego HyperStats JSON API i dodawać ich (insert-only) jako śledzone portfele, żeby istniejąca pętla z Inc 3 ciągnęła ich pozycje → claimy.

**Architecture:** Nowy lekki kolektor `collectors/hyperstats.py` (fetch leaderboard → filtr jakości → insert-only `Source(kind="hyperliquid")`). Dzienny job w schedulerze. Reużywa cały tor Inc 3 (`_hyperliquid_job` → `collect_wallet` → claimy) i `/api/wallets`. Bez przeglądarki, bez nowej tabeli/endpointu, bez zależności od Hermesa.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy, pytest. Testy w Dockerze (httpx mockowane — brak realnych calli w testach).

**Spec:** `docs/superpowers/specs/2026-06-05-argus-hyperstats-leaderboard-design.md`

---

## Konwencje
- **Brak lokalnego pythona.** Testy w Dockerze (PowerShell; trusted-host przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- `fetch_leaderboard(limit=100) -> list[dict]`; `_passes_filter(t, min_win_rate, min_trades, max_age_days, now) -> bool`; `sync_top_traders(session, top_n=20, min_win_rate=0.5, min_trades=50, max_age_days=14) -> dict`.

## Struktura plików
```
argus/argus/collectors/hyperstats.py   # NOWY — Task 1
argus/argus/main.py                     # MOD — Task 2 (_hyperstats_job + interval)
argus/.env.example                      # MOD — Task 2
argus/tests/test_hyperstats.py          # NOWY — Task 1
```

---

### Task 1: `collectors/hyperstats.py` (fetch + filter + sync)

**Files:** Create `argus/argus/collectors/hyperstats.py`; Test `argus/tests/test_hyperstats.py`

- [ ] **Step 1: Write failing test `argus/tests/test_hyperstats.py`**
```python
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from argus.models import Source
from argus.collectors.hyperstats import fetch_leaderboard, _passes_filter, sync_top_traders

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)

def _t(**kw):
    base = {"address": "0x" + "a"*40, "winRate": 0.7, "totalTrades": 100,
            "lastActivityAt": "2026-06-04T00:00:00Z", "totalPnl": 1000.0, "grade": "A"}
    base.update(kw)
    return base

def test_fetch_leaderboard_parses_and_limits():
    resp = MagicMock(); resp.raise_for_status.return_value = None
    resp.json.return_value = {"traders": [{"address": "0x1"}, {"address": "0x2"}]}
    with patch("argus.collectors.hyperstats.httpx.get", return_value=resp) as g:
        out = fetch_leaderboard(limit=50)
    assert len(out) == 2 and out[0]["address"] == "0x1"
    assert g.call_args.kwargs["params"]["limit"] == 50

def test_filter_accepts_good():
    assert _passes_filter(_t(), 0.5, 50, 14, NOW) is True

def test_filter_rejects_low_winrate():
    assert _passes_filter(_t(winRate=0.3), 0.5, 50, 14, NOW) is False

def test_filter_rejects_few_trades():
    assert _passes_filter(_t(totalTrades=10), 0.5, 50, 14, NOW) is False

def test_filter_rejects_stale():
    assert _passes_filter(_t(lastActivityAt="2026-05-01T00:00:00Z"), 0.5, 50, 14, NOW) is False

def test_filter_negative_pnl_low_grade_rejected():
    assert _passes_filter(_t(totalPnl=-5.0, grade="C"), 0.5, 50, 14, NOW) is False

def test_filter_negative_pnl_high_grade_ok():
    assert _passes_filter(_t(totalPnl=-5.0, grade="S+"), 0.5, 50, 14, NOW) is True

def test_sync_inserts_new_skips_existing_and_inactive(session):
    session.add(Source(kind="hyperliquid", handle="0x" + "b"*40, display_name="mine", active=True))
    session.add(Source(kind="hyperliquid", handle="0x" + "c"*40, display_name="off", active=False))
    session.commit()
    recent = datetime.now(timezone.utc).isoformat()
    def mk(addr, **kw):
        d = {"address": addr, "winRate": 0.7, "totalTrades": 100, "lastActivityAt": recent,
             "totalPnl": 1.0, "grade": "A"}
        d.update(kw); return d
    traders = [mk("0x" + "a"*40), mk("0x" + "b"*40), mk("0x" + "c"*40), mk("0x" + "d"*40, winRate=0.1)]
    with patch("argus.collectors.hyperstats.fetch_leaderboard", return_value=traders):
        stats = sync_top_traders(session, top_n=20)
    assert stats["added"] == 1
    assert stats["skipped_existing"] == 1
    assert stats["skipped_inactive"] == 1
    assert session.scalar(select(Source).where(Source.handle == "0x" + "a"*40)) is not None
    assert session.scalar(select(Source).where(Source.handle == "0x" + "c"*40)).active is False
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_hyperstats.py` → ImportError.

- [ ] **Step 3: Create `argus/argus/collectors/hyperstats.py`**
```python
import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select

from argus.models import Source

logger = logging.getLogger(__name__)
_URL = "https://v2-api.hyperstats.org/api/traders"

def fetch_leaderboard(limit: int = 100) -> list[dict]:
    r = httpx.get(_URL, params={"limit": limit}, timeout=30)
    r.raise_for_status()
    return r.json().get("traders", [])

def _passes_filter(t: dict, min_win_rate: float, min_trades: int, max_age_days: int, now: datetime) -> bool:
    try:
        if float(t.get("winRate", 0) or 0) < min_win_rate:
            return False
        if int(t.get("totalTrades", 0) or 0) < min_trades:
            return False
        la = t.get("lastActivityAt")
        if not la:
            return False
        dt = datetime.fromisoformat(str(la).replace("Z", "+00:00"))
        if dt < now - timedelta(days=max_age_days):
            return False
        grade = (t.get("grade") or "").upper()
        if float(t.get("totalPnl", 0) or 0) <= 0 and not grade.startswith(("A", "S")):
            return False
        return True
    except Exception:
        return False

def sync_top_traders(session, top_n: int = 20, min_win_rate: float = 0.5,
                     min_trades: int = 50, max_age_days: int = 14) -> dict:
    now = datetime.now(timezone.utc)
    stats = {"fetched": 0, "passed_filter": 0, "added": 0,
             "skipped_existing": 0, "skipped_inactive": 0, "errors": 0}
    try:
        traders = fetch_leaderboard(limit=max(top_n * 3, 100))
    except Exception as e:
        logger.warning("hyperstats fetch failed: %s", e)
        stats["errors"] += 1
        return stats
    stats["fetched"] = len(traders)
    passed = [t for t in traders if _passes_filter(t, min_win_rate, min_trades, max_age_days, now)]
    stats["passed_filter"] = len(passed)
    for t in passed[:top_n]:
        addr = (t.get("address") or "").lower()
        if not addr.startswith("0x"):
            continue
        existing = session.scalar(select(Source).where(Source.handle == addr))
        if existing is not None:
            if existing.active:
                stats["skipped_existing"] += 1
            else:
                logger.info("hyperstats: %s tracked but manually deactivated — skipping", addr)
                stats["skipped_inactive"] += 1
            continue
        grade = t.get("grade") or "?"
        session.add(Source(kind="hyperliquid", handle=addr,
                           display_name=f"HL {grade} {addr[:8]}", active=True))
        stats["added"] += 1
    session.commit()
    logger.info("hyperstats sync: %s", stats)
    return stats
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_hyperstats.py` → `7 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/collectors/hyperstats.py argus/tests/test_hyperstats.py
git commit -m "feat(argus): hyperstats collector (leaderboard -> insert-only tracked wallets)"
```

---

### Task 2: Scheduler wiring + env

**Files:** Modify `argus/argus/main.py`; Modify `argus/.env.example`

- [ ] **Step 1: Read `argus/argus/main.py`** to see the imports, the existing job functions, and where `sched.add_interval(...)` calls live.

- [ ] **Step 2: Edit `argus/argus/main.py`**
Add to the top imports: `from argus.collectors.hyperstats import sync_top_traders`. Add a job function alongside the others:
```python
def _hyperstats_job():
    import os
    with SessionLocal() as s:
        try:
            sync_top_traders(
                s,
                top_n=int(os.getenv("ARGUS_HYPERSTATS_TOP_N", "20")),
                min_win_rate=float(os.getenv("ARGUS_HYPERSTATS_MIN_WINRATE", "0.5")),
                min_trades=int(os.getenv("ARGUS_HYPERSTATS_MIN_TRADES", "50")),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("hyperstats job failed: %s", e)
```
Register it with the other `add_interval` calls (daily = 1440 min):
```python
    sched.add_interval("hyperstats", _hyperstats_job, minutes=1440)
```

- [ ] **Step 3: Edit `argus/.env.example`** — append:
```
ARGUS_HYPERSTATS_TOP_N=20
ARGUS_HYPERSTATS_MIN_WINRATE=0.5
ARGUS_HYPERSTATS_MIN_TRADES=50
```

- [ ] **Step 4: Verify import + full suite in Docker**
```
docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -c 'import argus.main; print(\"main ok\")' && python -m pytest -q"
```
Expected: `main ok` + full suite passes (prior 90 + 7 new = 97).

- [ ] **Step 5: Commit**
```
git add argus/argus/main.py argus/.env.example
git commit -m "feat(argus): wire daily hyperstats leaderboard sync job"
```

---

### Task 3: Redeploy + smoke

**Files:** (deployment)

- [ ] **Step 1: env-safe redeploy (preserve VPS .env — holds LLM keys)**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new ubuntu@84.235.174.129 "cp ~/argus/.env /tmp/argus.env.keep"
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cp /tmp/argus.env.keep ~/argus/.env && cd ~/argus && docker compose up -d --build"
```

- [ ] **Step 2: Smoke (after ~20s)** — trigger the hyperstats sync, confirm it discovers + adds HL wallets, then check they appear in /api/wallets:
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 20 && curl -sS http://localhost:8080/health; echo; cd ~/argus && docker compose exec -T app python -c \"
from argus.main import _hyperstats_job
from argus.db import SessionLocal
from argus.models import Source
from sqlalchemy import select, func
before = SessionLocal().scalar(select(func.count()).select_from(Source).where(Source.kind=='hyperliquid'))
_hyperstats_job()
s = SessionLocal()
after = s.scalar(select(func.count()).select_from(Source).where(Source.kind=='hyperliquid'))
print('hyperliquid sources before/after:', before, after)
for src in s.scalars(select(Source).where(Source.kind=='hyperliquid')).all()[:10]:
    print('  ', src.display_name, src.handle)
\"; echo '--- hyperstats sync log ---'; docker compose logs --since 90s app | grep -i 'hyperstats sync' | tail -3; echo '--- /api/wallets ---'; curl -sS http://localhost:8080/api/wallets | head -c 600"
```
Expected: health ok; `hyperliquid sources after` > before (new top traders added, e.g. labelled `HL S+ 0x...`); `hyperstats sync` log line with `{fetched, passed_filter, added, ...}`; `/api/wallets` lists them. (If HyperStats API is down → `errors:1`, added 0 — acceptable, retries next day.)

- [ ] **Step 3: Note for user** — new auto-discovered wallets appear in the dashboard „Śledzone portfele" panel; their positions get pulled by the existing 15-min hyperliquid job → position claims; Argus scorer ranks them by directional accuracy over the horizons.

---

## Self-Review

**Spec coverage:**
- HyperStats fetch (free JSON) → Task 1 `fetch_leaderboard` ✅
- Quality filter (winRate + min_trades + 14d activity + pnl/grade) → Task 1 `_passes_filter` ✅
- Insert-only into Source + explicit logging of 3 cases → Task 1 `sync_top_traders` ✅
- Observability stats dict (fetched/passed/added/skipped/errors) → Task 1 (returned + logged) ✅
- Grade = bootstrap only; scorer = real judge → reuse Inc 3 (no scoring change) ✅
- Daily job + env config → Task 2 ✅
- Reuse Inc-3 pipeline (`_hyperliquid_job` pulls positions), `/api/wallets` shows them → Task 3 smoke verifies ✅
- Unofficial-API resilience (fetch fail → log, skip, no scheduler crash) → Task 1 (`sync_top_traders` try/except) + Task 2 (`_hyperstats_job` try/except) ✅
- No new table/endpoint/browser → confirmed (no task adds them) ✅

**Placeholder scan:** brak — pełny kod w krokach. Task 3 = deployment.

**Type consistency:** `fetch_leaderboard(limit)`, `_passes_filter(t,min_win_rate,min_trades,max_age_days,now)`, `sync_top_traders(session,top_n,min_win_rate,min_trades,max_age_days)->dict` spójne (Task 1 def ↔ tests ↔ Task 2 `_hyperstats_job` call). `Source(kind="hyperliquid", handle, display_name, active)` zgodne z modelem Inc 1/3. Env names `ARGUS_HYPERSTATS_TOP_N/MIN_WINRATE/MIN_TRADES` spójne (Task 2 main ↔ .env.example).
