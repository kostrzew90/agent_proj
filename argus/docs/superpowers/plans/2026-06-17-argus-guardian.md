# Argus Guardian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight `argus-guardian` container on the same VPS that monitors Argus health every 5 minutes, restarts dead containers, sends Telegram alerts, and calls Gemini for unknown anomalies.

**Architecture:** Standalone Python container with Docker socket access, psycopg2 direct to Argus DB, APScheduler loop. Six checks: container liveness, queue runaway, LLM router, liq-listener silence, claims drought, scheduler heartbeat. Rules handle known issues; Gemini diagnoses unknown anomalies.

**Tech Stack:** Python 3.12, psycopg2-binary, docker SDK, httpx, apscheduler>=3.10

---

## File structure to create

```
argus/
  guardian/
    Dockerfile
    requirements.txt
    main.py          — APScheduler entry point, orchestrates all checks
    db.py            — psycopg2 connection + guardian_state init/read/update
    telegram.py      — send_alert(message) helper
    checks.py        — CheckResult dataclass + 6 check functions
    llm_diagnose.py  — Gemini diagnosis for UNKNOWN_ANOMALY
    tests/
      __init__.py
      test_checks.py — unit tests with mocked DB/Docker/httpx
      test_db.py     — unit tests for db.py
      test_llm_diagnose.py — unit tests for llm_diagnose.py
  argus/
    main.py          — MODIFY: add _heartbeat_job (every 5min, writes to guardian_state)
  docker-compose.yml — MODIFY: add argus-guardian service + explicit container_name on app/liq-listener
```

## Key decisions from spec review

- `docker-compose.yml` currently has no `container_name` on `app` or `liq-listener` — both need adding so Guardian can reference them by name
- No `argus-net` network defined in existing compose — the guardian service omits `networks:` block (all services share the default compose network automatically)
- `sched.add_interval()` takes `name, fn, *, minutes` — heartbeat job uses `minutes=5`
- `sqlalchemy.text` is already imported via `from sqlalchemy import select` indirectly, but must be added explicitly for `_heartbeat_job`
- DB password in compose is `argus` (not `arguspass` as stated in spec) — use `postgresql://argus:argus@db:5432/argus`

---

## Task 1: guardian/tests/__init__.py + db.py

**Files:** `argus/guardian/db.py`, `argus/guardian/tests/__init__.py`, `argus/guardian/tests/test_db.py`

### Step 1a: Write the failing tests first

Create `argus/guardian/tests/__init__.py` (empty).

Create `argus/guardian/tests/test_db.py`:

```python
from unittest.mock import MagicMock, patch, call
import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_conn(rows=None, description=None):
    """Return a mock psycopg2 connection whose cursor yields given rows."""
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.description = description or [("id",), ("last_queue_depth",)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


# ── init_db ───────────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_init_db_creates_table_and_seeds_row(mock_connect):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_connect.return_value = conn

    import db
    db.init_db()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS guardian_state" in sql for sql in executed_sqls)
    assert any("INSERT INTO guardian_state" in sql for sql in executed_sqls)
    conn.commit.assert_called_once()


# ── get_state ─────────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_get_state_returns_dict(mock_connect):
    conn, cur = _make_conn(
        rows=[(1, 0)],
        description=[("id",), ("last_queue_depth",)],
    )
    import db
    result = db.get_state(conn)
    assert isinstance(result, dict)
    assert result["id"] == 1
    assert result["last_queue_depth"] == 0


@patch("db.psycopg2.connect")
def test_get_state_returns_empty_dict_when_no_row(mock_connect):
    conn, cur = _make_conn(rows=[None], description=[("id",)])
    cur.fetchone.return_value = None
    import db
    result = db.get_state(conn)
    assert result == {}


# ── update_state ──────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_update_state_builds_correct_sql(mock_connect):
    conn, cur = _make_conn()
    import db
    db.update_state(conn, last_queue_depth=42, last_queue_growth_start=None)
    sql = cur.execute.call_args.args[0]
    assert "last_queue_depth = %s" in sql
    assert "last_queue_growth_start = %s" in sql
    assert "updated_at = now()" in sql
    conn.commit.assert_called_once()


@patch("db.psycopg2.connect")
def test_update_state_noop_when_no_kwargs(mock_connect):
    conn, cur = _make_conn()
    import db
    db.update_state(conn)
    cur.execute.assert_not_called()
```

Run (expected: all fail with ImportError — module doesn't exist yet):
```bash
cd argus
PYTHONPATH=guardian ARGUS_DB_URL=postgresql://argus:argus@db:5432/argus \
  python -m pytest guardian/tests/test_db.py -v --import-mode=prepend
```

### Step 1b: Implement db.py

Create `argus/guardian/db.py`:

```python
import os
import psycopg2


def get_conn():
    return psycopg2.connect(os.environ["ARGUS_DB_URL"])


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guardian_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    last_queue_depth INTEGER DEFAULT 0,
                    last_queue_growth_start TIMESTAMPTZ,
                    last_alert_container TIMESTAMPTZ,
                    last_alert_queue TIMESTAMPTZ,
                    last_alert_llm TIMESTAMPTZ,
                    last_alert_liq TIMESTAMPTZ,
                    last_alert_claims TIMESTAMPTZ,
                    last_alert_heartbeat TIMESTAMPTZ,
                    last_heartbeat_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute(
                "INSERT INTO guardian_state(id) VALUES(1) ON CONFLICT DO NOTHING"
            )
        conn.commit()


def get_state(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM guardian_state WHERE id = 1")
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else {}


def update_state(conn, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = %s" for k in kwargs)
    vals = list(kwargs.values())
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE guardian_state SET {sets}, updated_at = now() WHERE id = 1",
            vals,
        )
    conn.commit()
```

### Step 1c: Run tests — expect all pass

```bash
cd argus
PYTHONPATH=guardian ARGUS_DB_URL=postgresql://argus:argus@db:5432/argus \
  python -m pytest guardian/tests/test_db.py -v --import-mode=prepend
```

Expected output:
```
test_db.py::test_init_db_creates_table_and_seeds_row PASSED
test_db.py::test_get_state_returns_dict PASSED
test_db.py::test_get_state_returns_empty_dict_when_no_row PASSED
test_db.py::test_update_state_builds_correct_sql PASSED
test_db.py::test_update_state_noop_when_no_kwargs PASSED
5 passed
```

### Step 1d: Commit

```bash
git add argus/guardian/db.py argus/guardian/tests/__init__.py argus/guardian/tests/test_db.py
git commit -m "feat(guardian): db.py — psycopg2 connection + guardian_state CRUD"
```

---

## Task 2: telegram.py + CheckResult dataclass

**Files:** `argus/guardian/telegram.py`, `argus/guardian/checks.py` (skeleton), `argus/guardian/tests/test_checks.py` (partial)

### Step 2a: Write the failing tests first

Add to `argus/guardian/tests/test_checks.py` (create file):

```python
from unittest.mock import MagicMock, patch
import pytest


# ── telegram ─────────────────────────────────────────────────────────────────

class TestSendAlert:
    def test_no_token_does_nothing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        import importlib, telegram
        importlib.reload(telegram)  # pick up cleared env
        with patch("httpx.post") as mock_post:
            telegram.send_alert("hello")
            mock_post.assert_not_called()

    def test_with_env_calls_post(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
        import importlib, telegram
        importlib.reload(telegram)
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            telegram.send_alert("test message")
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "tok123" in call_kwargs.args[0]
            assert call_kwargs.kwargs["json"]["chat_id"] == "chat456"
            assert call_kwargs.kwargs["json"]["text"] == "test message"

    def test_httpx_error_swallowed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
        import importlib, telegram
        importlib.reload(telegram)
        with patch("httpx.post", side_effect=Exception("network error")):
            telegram.send_alert("oops")  # must not raise


# ── CheckResult ───────────────────────────────────────────────────────────────

class TestCheckResult:
    def test_dataclass_defaults(self):
        from checks import CheckResult, Status
        r = CheckResult(name="foo", status=Status.OK, message="")
        assert r.remediation is None
        assert r.logs_snippet is None

    def test_all_fields(self):
        from checks import CheckResult, Status
        r = CheckResult(
            name="container_liveness",
            status=Status.KNOWN_ISSUE,
            message="restarted",
            remediation="docker restart app",
            logs_snippet="some logs",
        )
        assert r.name == "container_liveness"
        assert r.status == Status.KNOWN_ISSUE
```

Run (expected: ImportError — files don't exist):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestSendAlert \
  guardian/tests/test_checks.py::TestCheckResult -v --import-mode=prepend
```

### Step 2b: Implement telegram.py

Create `argus/guardian/telegram.py`:

```python
import os
import httpx

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_alert(message: str) -> None:
    if not _TOKEN or not _CHAT:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT, "text": message},
            timeout=10,
        )
    except Exception:
        pass
```

### Step 2c: Implement checks.py skeleton (Status + CheckResult only)

Create `argus/guardian/checks.py`:

```python
import os
from dataclasses import dataclass
from enum import Enum

import docker
import httpx

from db import update_state

_APP_CONTAINER = os.environ.get("ARGUS_APP_CONTAINER", "argus-app")
_LIQ_CONTAINER = os.environ.get("ARGUS_LIQ_CONTAINER", "argus-liq-listener")
_HEALTH_URL = os.environ.get("ARGUS_HEALTH_URL", "http://app:8080/health")


class Status(Enum):
    OK = "ok"
    KNOWN_ISSUE = "known_issue"
    UNKNOWN_ANOMALY = "unknown_anomaly"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    remediation: str | None = None
    logs_snippet: str | None = None
```

(check functions will be added in Tasks 3–7)

### Step 2d: Run tests — expect pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestSendAlert \
  guardian/tests/test_checks.py::TestCheckResult -v --import-mode=prepend
```

Expected: 5 passed.

### Step 2e: Commit

```bash
git add argus/guardian/telegram.py argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): telegram.py + CheckResult dataclass"
```

---

## Task 3: checks.py — check_container_liveness

**File:** `argus/guardian/checks.py` (add function)

### Step 3a: Write failing tests

Append to `argus/guardian/tests/test_checks.py`:

```python
# ── check_container_liveness ─────────────────────────────────────────────────

class TestCheckContainerLiveness:
    def _make_docker_client(self, statuses=None, raise_not_found=None):
        """statuses: dict of container_name -> status string"""
        statuses = statuses or {}
        client = MagicMock()

        def get_container(name):
            if raise_not_found and name in raise_not_found:
                raise docker.errors.NotFound(name)
            c = MagicMock()
            c.status = statuses.get(name, "running")
            return c

        client.containers.get.side_effect = get_container
        return client

    @patch("checks.docker.from_env")
    def test_container_not_found_returns_known_issue(self, mock_docker):
        mock_docker.return_value = self._make_docker_client(
            raise_not_found=["argus-app"]
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "not found" in result.message

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_container_stopped_restarts_and_known_issue(self, mock_docker, mock_get):
        client = self._make_docker_client(statuses={"argus-app": "exited"})
        mock_docker.return_value = client
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "Restarted" in result.message
        client.containers.get("argus-app").restart.assert_called_once()

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_health_500_restarts_app_and_known_issue(self, mock_docker, mock_get):
        client = self._make_docker_client(
            statuses={"argus-app": "running", "argus-liq-listener": "running"}
        )
        mock_docker.return_value = client
        mock_get.return_value = MagicMock(
            status_code=500,
            json=MagicMock(return_value={"status": "error"}),
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "health failed" in result.message

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_all_ok_returns_ok(self, mock_docker, mock_get):
        client = self._make_docker_client(
            statuses={"argus-app": "running", "argus-liq-listener": "running"}
        )
        mock_docker.return_value = client
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "ok"}),
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.OK
```

Run (expected: fail — function doesn't exist yet):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckContainerLiveness \
  -v --import-mode=prepend
```

### Step 3b: Implement check_container_liveness

Append to `argus/guardian/checks.py`:

```python
def check_container_liveness(state: dict) -> "CheckResult":
    client = docker.from_env()
    for cname in (_APP_CONTAINER, _LIQ_CONTAINER):
        try:
            c = client.containers.get(cname)
        except docker.errors.NotFound:
            return CheckResult(
                name="container_liveness",
                status=Status.KNOWN_ISSUE,
                message=f"⚠️ argus-guardian: container {cname} not found.",
            )
        if c.status != "running":
            c.restart()
            return CheckResult(
                name="container_liveness",
                status=Status.KNOWN_ISSUE,
                message=f"⚠️ argus-guardian: {cname} was {c.status}. Restarted.",
                remediation=f"docker restart {cname}",
            )
    # Health endpoint check
    try:
        r = httpx.get(_HEALTH_URL, timeout=5)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        if r.json().get("status") != "ok":
            raise ValueError(f"payload: {r.text[:100]}")
    except Exception as e:
        client.containers.get(_APP_CONTAINER).restart()
        return CheckResult(
            name="container_liveness",
            status=Status.KNOWN_ISSUE,
            message=f"⚠️ argus-guardian: health failed ({e}). Restarted app.",
            remediation=f"docker restart {_APP_CONTAINER}",
        )
    return CheckResult(name="container_liveness", status=Status.OK, message="")
```

### Step 3c: Run tests — expect pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckContainerLiveness \
  -v --import-mode=prepend
```

Expected: 4 passed.

### Step 3d: Commit

```bash
git add argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): check_container_liveness"
```

---

## Task 4: checks.py — check_queue_runaway

**File:** `argus/guardian/checks.py` (add function)

### Step 4a: Write failing tests

Append to `argus/guardian/tests/test_checks.py`:

```python
# ── check_queue_runaway ───────────────────────────────────────────────────────

class TestCheckQueueRunaway:
    def _make_conn(self, depth):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (depth,)
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    @patch("checks.update_state")
    def test_growth_under_30min_returns_ok(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=50)
        state = {
            "last_queue_depth": 40,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=10),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK

    @patch("checks.update_state")
    def test_growth_over_30min_returns_known_issue(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=100)
        state = {
            "last_queue_depth": 40,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=35),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.KNOWN_ISSUE
        assert "30min+" in result.message

    @patch("checks.update_state")
    def test_depth_drops_resets_growth_start(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=20)
        state = {
            "last_queue_depth": 50,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=40),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK
        # update_state called with last_queue_growth_start=None
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs.get("last_queue_growth_start") is None

    @patch("checks.update_state")
    def test_first_run_no_growth_start_returns_ok(self, mock_update):
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=10)
        state = {"last_queue_depth": 0, "last_queue_growth_start": None}
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK
```

Run (expected: fail):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckQueueRunaway \
  -v --import-mode=prepend
```

### Step 4b: Implement check_queue_runaway

Append to `argus/guardian/checks.py` (after imports, add `from datetime import datetime, timezone, timedelta` at top if not present):

```python
from datetime import datetime, timezone, timedelta


def check_queue_runaway(conn, state: dict) -> "CheckResult":
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM llm_queue WHERE status='pending'")
        depth = cur.fetchone()[0]

    prev_depth = state.get("last_queue_depth") or 0
    growth_start = state.get("last_queue_growth_start")
    now = datetime.now(timezone.utc)

    if depth > prev_depth:
        if growth_start is None:
            growth_start = now
        update_state(conn, last_queue_depth=depth, last_queue_growth_start=growth_start)
        growing_for = (now - growth_start).total_seconds()
        if growing_for >= 1800:  # 30 minutes
            return CheckResult(
                name="queue_runaway",
                status=Status.KNOWN_ISSUE,
                message=(
                    f"📬 argus-guardian: llm_queue growing 30min+ "
                    f"(now {depth}, was {prev_depth}). Check llm_batch job."
                ),
            )
    else:
        update_state(conn, last_queue_depth=depth, last_queue_growth_start=None)

    return CheckResult(name="queue_runaway", status=Status.OK, message="")
```

Note: add `from datetime import datetime, timezone, timedelta` near the top of checks.py if not already there.

### Step 4c: Run tests — expect pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckQueueRunaway \
  -v --import-mode=prepend
```

Expected: 4 passed.

### Step 4d: Commit

```bash
git add argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): check_queue_runaway — growth-rate 30min detection"
```

---

## Task 5: checks.py — check_llm_router

**File:** `argus/guardian/checks.py` (add function)

### Step 5a: Write failing tests

Append to `argus/guardian/tests/test_checks.py`:

```python
# ── check_llm_router ──────────────────────────────────────────────────────────

class TestCheckLlmRouter:
    def _make_conn(self, ok_count, fail_count, total):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (ok_count, fail_count, total)
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    def test_total_under_3_returns_ok(self):
        from checks import check_llm_router, Status
        conn = self._make_conn(ok_count=0, fail_count=2, total=2)
        result = check_llm_router(conn, {})
        assert result.status == Status.OK

    def test_all_failed_returns_known_issue(self):
        from checks import check_llm_router, Status
        conn = self._make_conn(ok_count=0, fail_count=10, total=10)
        result = check_llm_router(conn, {})
        assert result.status == Status.KNOWN_ISSUE
        assert "all-failed" in result.message

    def test_high_failure_rate_returns_unknown_anomaly(self):
        from checks import check_llm_router, Status
        # 85% fail rate: 17 fail, 3 ok, total 20
        conn = self._make_conn(ok_count=3, fail_count=17, total=20)
        result = check_llm_router(conn, {})
        assert result.status == Status.UNKNOWN_ANOMALY
        assert "high failure rate" in result.message

    def test_50_percent_failure_returns_ok(self):
        from checks import check_llm_router, Status
        conn = self._make_conn(ok_count=5, fail_count=5, total=10)
        result = check_llm_router(conn, {})
        assert result.status == Status.OK
```

Run (expected: fail):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckLlmRouter \
  -v --import-mode=prepend
```

### Step 5b: Implement check_llm_router

Append to `argus/guardian/checks.py`:

```python
def check_llm_router(conn, state: dict) -> "CheckResult":
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                count(*) FILTER (WHERE ok = true)  AS ok_count,
                count(*) FILTER (WHERE ok = false) AS fail_count,
                count(*) AS total
            FROM llm_calls
            WHERE ts > now() - interval '1 hour'
        """)
        row = cur.fetchone()
    ok_count, fail_count, total = row

    if total < 3:
        return CheckResult(name="llm_router", status=Status.OK, message="")

    if ok_count == 0:
        return CheckResult(
            name="llm_router",
            status=Status.KNOWN_ISSUE,
            message=(
                f"🔴 argus-guardian: LLM all-failed "
                f"({fail_count} errors/1h, 0 success). Providers exhausted."
            ),
        )

    if total > 0 and fail_count / total > 0.8:
        return CheckResult(
            name="llm_router",
            status=Status.UNKNOWN_ANOMALY,
            message=f"🟡 argus-guardian: LLM high failure rate ({fail_count}/{total}/1h).",
            logs_snippet="llm_router_degraded",
        )

    return CheckResult(name="llm_router", status=Status.OK, message="")
```

### Step 5c: Run tests — expect pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckLlmRouter \
  -v --import-mode=prepend
```

Expected: 4 passed.

### Step 5d: Commit

```bash
git add argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): check_llm_router — all-fail + high-failure-rate detection"
```

---

## Task 6: checks.py — check_liq_silence

**File:** `argus/guardian/checks.py` (add function)

### Step 6a: Write failing tests

Append to `argus/guardian/tests/test_checks.py`:

```python
# ── check_liq_silence ─────────────────────────────────────────────────────────

class TestCheckLiqSilence:
    def _make_conn(self, last_liq_age_h, last_item_age_m=None):
        """last_liq_age_h: hours ago for last liquidation (None = no rows)
           last_item_age_m: minutes ago for last item (None = no rows)"""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        liq_ts = now - timedelta(hours=last_liq_age_h) if last_liq_age_h is not None else None
        item_ts = now - timedelta(minutes=last_item_age_m) if last_item_age_m is not None else None

        conn = MagicMock()
        cur = MagicMock()
        # Two fetchone calls: first for liquidations, second for items
        cur.fetchone.side_effect = [(liq_ts,), (item_ts,)]
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    def test_recent_liq_returns_ok(self):
        from checks import check_liq_silence, Status
        conn = self._make_conn(last_liq_age_h=2)
        result = check_liq_silence(conn, {})
        assert result.status == Status.OK

    def test_old_liq_recent_items_known_issue(self):
        from checks import check_liq_silence, Status
        conn = self._make_conn(last_liq_age_h=8, last_item_age_m=10)
        result = check_liq_silence(conn, {})
        assert result.status == Status.KNOWN_ISSUE
        assert "liq-listener silent" in result.message

    def test_old_liq_old_items_unknown_anomaly(self):
        from checks import check_liq_silence, Status
        conn = self._make_conn(last_liq_age_h=10, last_item_age_m=400)
        result = check_liq_silence(conn, {})
        assert result.status == Status.UNKNOWN_ANOMALY
        assert "broader outage" in result.message
```

Run (expected: fail):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckLiqSilence \
  -v --import-mode=prepend
```

### Step 6b: Implement check_liq_silence

Append to `argus/guardian/checks.py`:

```python
def check_liq_silence(conn, state: dict) -> "CheckResult":
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT max(ts) FROM liquidations")
        last_liq = cur.fetchone()[0]
        cur.execute("SELECT max(fetched_at) FROM items")
        last_item = cur.fetchone()[0]

    if last_liq and (now - last_liq) < timedelta(hours=6):
        return CheckResult(name="liq_silence", status=Status.OK, message="")

    if last_item and (now - last_item) < timedelta(minutes=30):
        return CheckResult(
            name="liq_silence",
            status=Status.KNOWN_ISSUE,
            message=(
                "📡 argus-guardian: liq-listener silent 6h+ "
                "(items still flowing). Check HL WebSocket."
            ),
        )

    return CheckResult(
        name="liq_silence",
        status=Status.UNKNOWN_ANOMALY,
        message=(
            "📡 argus-guardian: liq-listener silent AND no items ingested. "
            "Broader outage?"
        ),
        logs_snippet="liq_and_items_silent",
    )
```

### Step 6c: Run tests — expect pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py::TestCheckLiqSilence \
  -v --import-mode=prepend
```

Expected: 3 passed.

### Step 6d: Commit

```bash
git add argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): check_liq_silence — two-signal cross-check"
```

---

## Task 7: checks.py — check_claims_drought + check_scheduler_heartbeat

**File:** `argus/guardian/checks.py` (add two functions)

### Step 7a: Write failing tests

Append to `argus/guardian/tests/test_checks.py`:

```python
# ── check_claims_drought ──────────────────────────────────────────────────────

class TestCheckClaimsDrought:
    def _make_conn(self, claims, processed):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [(claims,), (processed,)]
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    def test_processed_under_5_returns_ok(self):
        from checks import check_claims_drought, Status
        conn = self._make_conn(claims=0, processed=3)
        result = check_claims_drought(conn, {})
        assert result.status == Status.OK

    def test_ratio_above_threshold_returns_ok(self):
        from checks import check_claims_drought, Status
        conn = self._make_conn(claims=8, processed=100)  # 8% — normal
        result = check_claims_drought(conn, {})
        assert result.status == Status.OK

    def test_near_zero_ratio_returns_unknown_anomaly(self):
        from checks import check_claims_drought, Status
        conn = self._make_conn(claims=0, processed=100)  # 0% — drought
        result = check_claims_drought(conn, {})
        assert result.status == Status.UNKNOWN_ANOMALY
        assert "claims/processed ratio" in result.message

    def test_ratio_just_below_threshold_returns_unknown_anomaly(self):
        from checks import check_claims_drought, Status
        conn = self._make_conn(claims=2, processed=100)  # 2% < 5%
        result = check_claims_drought(conn, {})
        assert result.status == Status.UNKNOWN_ANOMALY


# ── check_scheduler_heartbeat ─────────────────────────────────────────────────

class TestCheckSchedulerHeartbeat:
    def test_no_heartbeat_yet_returns_ok(self):
        """First run — guardian_state has no heartbeat row yet."""
        from checks import check_scheduler_heartbeat, Status
        result = check_scheduler_heartbeat({"last_heartbeat_at": None})
        assert result.status == Status.OK

    def test_recent_heartbeat_returns_ok(self):
        from datetime import datetime, timezone, timedelta
        from checks import check_scheduler_heartbeat, Status
        state = {"last_heartbeat_at": datetime.now(timezone.utc) - timedelta(minutes=3)}
        result = check_scheduler_heartbeat(state)
        assert result.status == Status.OK

    def test_stale_heartbeat_returns_known_issue(self):
        from datetime import datetime, timezone, timedelta
        from checks import check_scheduler_heartbeat, Status
        state = {"last_heartbeat_at": datetime.now(timezone.utc) - timedelta(minutes=20)}
        result = check_scheduler_heartbeat(state)
        assert result.status == Status.KNOWN_ISSUE
        assert "silent 15min+" in result.message
        assert result.remediation is not None
```

Run (expected: fail):
```bash
cd argus
PYTHONPATH=guardian python -m pytest \
  guardian/tests/test_checks.py::TestCheckClaimsDrought \
  guardian/tests/test_checks.py::TestCheckSchedulerHeartbeat \
  -v --import-mode=prepend
```

### Step 7b: Implement both functions

Append to `argus/guardian/checks.py`:

```python
def check_claims_drought(conn, state: dict) -> "CheckResult":
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM claims WHERE entry_ts > now() - interval '12 hours'"
        )
        claims = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM llm_queue "
            "WHERE status='done' AND processed_at > now() - interval '12 hours'"
        )
        processed = cur.fetchone()[0]

    if processed < 5:
        return CheckResult(name="claims_drought", status=Status.OK, message="")

    ratio = claims / processed
    if ratio < 0.05:
        return CheckResult(
            name="claims_drought",
            status=Status.UNKNOWN_ANOMALY,
            message=(
                f"🌵 argus-guardian: claims/processed ratio {ratio:.3f} (12h). "
                "Extractor degraded?"
            ),
            logs_snippet="claims_drought",
        )
    return CheckResult(name="claims_drought", status=Status.OK, message="")


def check_scheduler_heartbeat(state: dict) -> "CheckResult":
    last_hb = state.get("last_heartbeat_at")
    now = datetime.now(timezone.utc)
    if last_hb is None:
        return CheckResult(name="scheduler_heartbeat", status=Status.OK, message="")
    if (now - last_hb) > timedelta(minutes=15):
        return CheckResult(
            name="scheduler_heartbeat",
            status=Status.KNOWN_ISSUE,
            message=(
                "💀 argus-guardian: Argus scheduler silent 15min+ "
                "(container running). Restarting."
            ),
            remediation=f"docker restart {_APP_CONTAINER}",
        )
    return CheckResult(name="scheduler_heartbeat", status=Status.OK, message="")
```

### Step 7c: Run all checks tests — expect all pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_checks.py -v --import-mode=prepend
```

Expected: all test classes pass (no failures).

### Step 7d: Commit

```bash
git add argus/guardian/checks.py argus/guardian/tests/test_checks.py
git commit -m "feat(guardian): check_claims_drought + check_scheduler_heartbeat"
```

---

## Task 8: llm_diagnose.py

**Files:** `argus/guardian/llm_diagnose.py`, `argus/guardian/tests/test_llm_diagnose.py`

### Step 8a: Write failing tests first

Create `argus/guardian/tests/test_llm_diagnose.py`:

```python
from unittest.mock import patch, MagicMock
import pytest


class TestDiagnose:
    def test_no_api_key_returns_unavailable(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)
        result = llm_diagnose.diagnose("some_anomaly", "some logs")
        assert "unavailable" in result

    def test_long_logs_truncated_to_50_lines(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        many_lines = "\n".join(f"line {i}" for i in range(200))
        captured_prompt = {}

        def mock_post(url, json, timeout):
            captured_prompt["prompt"] = json["contents"][0]["parts"][0]["text"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "diagnosis here"}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            llm_diagnose.diagnose("test_anomaly", many_lines)

        prompt_lines = captured_prompt["prompt"].count("\n")
        # 50 log lines + prompt overhead — rough check that it's not 200 lines
        assert "line 199" in captured_prompt["prompt"]  # last line present
        assert "line 0" not in captured_prompt["prompt"]  # first lines truncated

    def test_logs_truncated_to_10kb(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        # 200 lines of 100 chars each = 20KB, should truncate
        big_logs = "\n".join("x" * 100 for _ in range(200))
        captured_prompt = {}

        def mock_post(url, json, timeout):
            captured_prompt["text"] = json["contents"][0]["parts"][0]["text"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            llm_diagnose.diagnose("test_anomaly", big_logs)

        assert len(captured_prompt["text"]) <= 10_200  # 10KB logs + prompt header

    def test_httpx_error_returns_unavailable(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)
        with patch("httpx.post", side_effect=Exception("timeout")):
            result = llm_diagnose.diagnose("anomaly", "logs")
        assert "unavailable" in result

    def test_successful_call_returns_text(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        def mock_post(url, json, timeout):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "Queue backed up due to rate limit."}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            result = llm_diagnose.diagnose("queue_runaway", "some logs")
        assert result == "Queue backed up due to rate limit."
```

Run (expected: all fail — module doesn't exist):
```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_llm_diagnose.py -v --import-mode=prepend
```

### Step 8b: Implement llm_diagnose.py

Create `argus/guardian/llm_diagnose.py`:

```python
import os
import httpx

_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def diagnose(anomaly_type: str, logs_snippet: str) -> str:
    """Call Gemini free tier, return 2-3 sentence diagnosis for Telegram.

    Returns "LLM diagnosis unavailable (...)" on any error.
    """
    if not _GEMINI_KEY:
        return "LLM diagnosis unavailable (no API key)"

    lines = logs_snippet.splitlines()[-50:]
    truncated = "\n".join(lines)[-10_000:]
    prompt = (
        f"Argus agent anomaly: {anomaly_type}\n\n"
        f"Recent logs:\n{truncated}\n\n"
        "What likely caused this? Answer in 2-3 sentences max."
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={_GEMINI_KEY}"
    )
    try:
        r = httpx.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 150, "temperature": 0},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"LLM diagnosis unavailable ({e})"
```

### Step 8c: Run tests — expect all pass

```bash
cd argus
PYTHONPATH=guardian python -m pytest guardian/tests/test_llm_diagnose.py -v --import-mode=prepend
```

Expected: 5 passed.

### Step 8d: Commit

```bash
git add argus/guardian/llm_diagnose.py argus/guardian/tests/test_llm_diagnose.py
git commit -m "feat(guardian): llm_diagnose.py — Gemini diagnosis for UNKNOWN_ANOMALY"
```

---

## Task 9: guardian/main.py — orchestration loop

**File:** `argus/guardian/main.py`

No unit tests for main.py (it's pure orchestration glue — integration tested via deploy). Verify manually after Task 12.

### Step 9a: Implement main.py

Create `argus/guardian/main.py`:

```python
import os
import logging
import docker
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler

from db import init_db, get_conn, get_state, update_state
from telegram import send_alert
from checks import (
    Status,
    check_container_liveness,
    check_queue_runaway,
    check_llm_router,
    check_liq_silence,
    check_claims_drought,
    check_scheduler_heartbeat,
)
from llm_diagnose import diagnose

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("argus-guardian")

_APP_CONTAINER = os.environ.get("ARGUS_APP_CONTAINER", "argus-app")

# Cooldown per check: (state_key, timedelta)
_COOLDOWNS = {
    "container_liveness":  ("last_alert_container",  timedelta(minutes=30)),
    "queue_runaway":       ("last_alert_queue",       timedelta(hours=2)),
    "llm_router":          ("last_alert_llm",         timedelta(hours=2)),
    "liq_silence":         ("last_alert_liq",         timedelta(hours=6)),
    "claims_drought":      ("last_alert_claims",      timedelta(hours=12)),
    "scheduler_heartbeat": ("last_alert_heartbeat",   timedelta(minutes=30)),
}


def _get_app_logs() -> str:
    try:
        client = docker.from_env()
        c = client.containers.get(_APP_CONTAINER)
        return c.logs(tail=100).decode("utf-8", errors="replace")
    except Exception as e:
        return f"(could not fetch logs: {e})"


def _run_checks() -> None:
    logger.info("running checks")
    try:
        conn = get_conn()
    except Exception as e:
        logger.error("DB connect failed: %s", e)
        send_alert(f"🚨 argus-guardian: cannot connect to DB: {e}")
        return

    try:
        state = get_state(conn)
    except Exception as e:
        logger.error("get_state failed: %s", e)
        conn.close()
        return

    check_fns = [
        lambda: check_container_liveness(state),
        lambda: check_queue_runaway(conn, state),
        lambda: check_llm_router(conn, state),
        lambda: check_liq_silence(conn, state),
        lambda: check_claims_drought(conn, state),
        lambda: check_scheduler_heartbeat(state),
    ]

    now = datetime.now(timezone.utc)

    for check_fn in check_fns:
        try:
            result = check_fn()
        except Exception as e:
            logger.error("check raised exception: %s", e)
            continue

        if result.status == Status.OK:
            logger.debug("check %s: OK", result.name)
            continue

        state_key, cooldown = _COOLDOWNS[result.name]
        last_alert = state.get(state_key)

        if last_alert and (now - last_alert) < cooldown:
            logger.info("check %s: suppressed (cooldown)", result.name)
            continue

        message = result.message

        if result.status == Status.UNKNOWN_ANOMALY:
            logs = _get_app_logs()
            diagnosis = diagnose(result.name, logs)
            message += f"\n\nGemini diagnosis: {diagnosis}"

        # For scheduler heartbeat: trigger docker restart
        if result.remediation and result.name == "scheduler_heartbeat":
            try:
                client = docker.from_env()
                client.containers.get(_APP_CONTAINER).restart()
                logger.info("restarted %s due to silent scheduler", _APP_CONTAINER)
            except Exception as e:
                message += f"\n(restart failed: {e})"
                logger.error("restart failed: %s", e)

        send_alert(message)
        try:
            update_state(conn, **{state_key: now})
        except Exception as e:
            logger.error("update_state failed: %s", e)
        logger.info("alert sent: %s [%s]", result.name, result.status.value)

    conn.close()


def main() -> None:
    logger.info("argus-guardian starting")
    init_db()

    interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(_run_checks, "interval", seconds=interval, id="guardian")
    logger.info("scheduled every %ds", interval)

    _run_checks()  # run immediately on startup
    sched.start()


if __name__ == "__main__":
    main()
```

### Step 9b: Commit

```bash
git add argus/guardian/main.py
git commit -m "feat(guardian): main.py — APScheduler orchestration loop"
```

---

## Task 10: Dockerfile + requirements.txt

**Files:** `argus/guardian/Dockerfile`, `argus/guardian/requirements.txt`

### Step 10a: Create requirements.txt

Create `argus/guardian/requirements.txt`:

```
apscheduler>=3.10
docker>=7.0
httpx>=0.27
psycopg2-binary>=2.9
```

### Step 10b: Create Dockerfile

Create `argus/guardian/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

### Step 10c: Verify Dockerfile syntax

```bash
cd argus
docker compose config 2>&1 | head -20
```

(Will fail until Task 11 updates compose — that's expected. Just verify no syntax error in Dockerfile itself.)

Alternatively:
```bash
docker build -f argus/guardian/Dockerfile argus/guardian/ --no-cache -t argus-guardian-test 2>&1 | tail -5
```

Expected last line: `Successfully built <hash>` or `=> exporting to image` (BuildKit).

### Step 10d: Commit

```bash
git add argus/guardian/Dockerfile argus/guardian/requirements.txt
git commit -m "feat(guardian): Dockerfile + requirements.txt — Python 3.12-slim"
```

---

## Task 11: docker-compose.yml — add guardian + explicit container_names

**File:** `argus/docker-compose.yml`

### Step 11a: Read current file (already done above — shown for reference)

Current state:
- `app` service: no `container_name`, no `restart`
- `liq-listener` service: no `container_name`
- No `argus-guardian` service
- No explicit network definition (default compose network used by all services)

### Step 11b: Implement changes

Edit `argus/docker-compose.yml` to:

1. Add `container_name: argus-app` and `restart: unless-stopped` to `app` service
2. Add `container_name: argus-liq-listener` to `liq-listener` service
3. Add `argus-guardian` service

Full updated file:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: argus
      POSTGRES_PASSWORD: argus
      POSTGRES_DB: argus
    volumes: ["argus-pg:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U argus"]
      interval: 5s
      retries: 10

  app:
    build: .
    container_name: argus-app
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    ports: ["8080:8080"]
    restart: unless-stopped

  liq-listener:
    build: .
    container_name: argus-liq-listener
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    command: ["python", "-m", "argus.liquidations.hl_listener"]
    restart: unless-stopped

  argus-guardian:
    build:
      context: ./guardian
    container_name: argus-guardian
    restart: unless-stopped
    depends_on:
      - app
      - db
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      ARGUS_DB_URL: postgresql://argus:argus@db:5432/argus
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      GEMINI_MODEL: ${ARGUS_GEMINI_MODEL:-gemini-2.5-flash}
      CHECK_INTERVAL_SECONDS: "300"
      ARGUS_APP_CONTAINER: argus-app
      ARGUS_LIQ_CONTAINER: argus-liq-listener
      ARGUS_HEALTH_URL: http://app:8080/health

volumes:
  argus-pg:
```

Note: `ARGUS_DB_URL` uses password `argus` (matching the `db` service's `POSTGRES_PASSWORD`), not `arguspass` (which was a spec typo).

### Step 11c: Verify compose config

```bash
cd argus
docker compose config
```

Expected: YAML output with no errors, all 4 services listed.

### Step 11d: Commit

```bash
git add argus/docker-compose.yml
git commit -m "feat(guardian): add argus-guardian service + container_name on app/liq-listener"
```

---

## Task 12: argus/main.py — add _heartbeat_job

**File:** `argus/argus/main.py`

### Step 12a: Check sqlalchemy.text import

Current imports in `argus/argus/main.py` include `from sqlalchemy import select` but not `text`. The `_heartbeat_job` needs `text`.

### Step 12b: Apply surgical changes

Two edits:

**Edit 1:** Add `text` to the sqlalchemy import on line 16:
```python
# Before:
from sqlalchemy import select
# After:
from sqlalchemy import select, text
```

**Edit 2:** Add `_heartbeat_job` function after `_hyperstats_job` (before `bootstrap`), and register it in `bootstrap()`.

Add function (after `_hyperstats_job`, before `bootstrap`):
```python
def _heartbeat_job():
    with SessionLocal() as s:
        s.execute(
            text(
                "UPDATE guardian_state SET last_heartbeat_at = now(), "
                "updated_at = now() WHERE id = 1"
            )
        )
        s.commit()
```

Add registration inside `bootstrap()` after the last `sched.add_interval` call:
```python
    sched.add_interval("heartbeat", _heartbeat_job, minutes=5)
```

(The UPDATE is a no-op if `guardian_state` doesn't exist — PostgreSQL raises an error only on syntax issues, not on UPDATE that matches 0 rows. However, if the table doesn't exist, the UPDATE will fail with a relation-not-found error. Wrap in try/except to make it silent until guardian starts:)

```python
def _heartbeat_job():
    try:
        with SessionLocal() as s:
            s.execute(
                text(
                    "UPDATE guardian_state SET last_heartbeat_at = now(), "
                    "updated_at = now() WHERE id = 1"
                )
            )
            s.commit()
    except Exception:
        pass  # guardian_state may not exist yet; harmless
```

### Step 12c: Verify no import errors

```bash
cd argus
python -c "from argus.main import bootstrap" 2>&1
```

Expected: no output (clean import).

### Step 12d: Commit

```bash
git add argus/argus/main.py
git commit -m "feat(argus): _heartbeat_job — writes last_heartbeat_at to guardian_state every 5min"
```

---

## Task 13: Full test suite pass

Run all guardian tests together:

```bash
cd argus
PYTHONPATH=guardian ARGUS_DB_URL=postgresql://argus:argus@localhost:5432/argus \
  python -m pytest guardian/tests/ -v --import-mode=prepend
```

Expected output summary:
```
test_db.py::test_init_db_creates_table_and_seeds_row PASSED
test_db.py::test_get_state_returns_dict PASSED
test_db.py::test_get_state_returns_empty_dict_when_no_row PASSED
test_db.py::test_update_state_builds_correct_sql PASSED
test_db.py::test_update_state_noop_when_no_kwargs PASSED
test_checks.py::TestSendAlert::test_no_token_does_nothing PASSED
test_checks.py::TestSendAlert::test_with_env_calls_post PASSED
test_checks.py::TestSendAlert::test_httpx_error_swallowed PASSED
test_checks.py::TestCheckResult::test_dataclass_defaults PASSED
test_checks.py::TestCheckResult::test_all_fields PASSED
test_checks.py::TestCheckContainerLiveness::test_container_not_found_returns_known_issue PASSED
test_checks.py::TestCheckContainerLiveness::test_container_stopped_restarts_and_known_issue PASSED
test_checks.py::TestCheckContainerLiveness::test_health_500_restarts_app_and_known_issue PASSED
test_checks.py::TestCheckContainerLiveness::test_all_ok_returns_ok PASSED
test_checks.py::TestCheckQueueRunaway::test_growth_under_30min_returns_ok PASSED
test_checks.py::TestCheckQueueRunaway::test_growth_over_30min_returns_known_issue PASSED
test_checks.py::TestCheckQueueRunaway::test_depth_drops_resets_growth_start PASSED
test_checks.py::TestCheckQueueRunaway::test_first_run_no_growth_start_returns_ok PASSED
test_checks.py::TestCheckLlmRouter::test_total_under_3_returns_ok PASSED
test_checks.py::TestCheckLlmRouter::test_all_failed_returns_known_issue PASSED
test_checks.py::TestCheckLlmRouter::test_high_failure_rate_returns_unknown_anomaly PASSED
test_checks.py::TestCheckLlmRouter::test_50_percent_failure_returns_ok PASSED
test_checks.py::TestCheckLiqSilence::test_recent_liq_returns_ok PASSED
test_checks.py::TestCheckLiqSilence::test_old_liq_recent_items_known_issue PASSED
test_checks.py::TestCheckLiqSilence::test_old_liq_old_items_unknown_anomaly PASSED
test_checks.py::TestCheckClaimsDrought::test_processed_under_5_returns_ok PASSED
test_checks.py::TestCheckClaimsDrought::test_ratio_above_threshold_returns_ok PASSED
test_checks.py::TestCheckClaimsDrought::test_near_zero_ratio_returns_unknown_anomaly PASSED
test_checks.py::TestCheckClaimsDrought::test_ratio_just_below_threshold_returns_unknown_anomaly PASSED
test_checks.py::TestCheckSchedulerHeartbeat::test_no_heartbeat_yet_returns_ok PASSED
test_checks.py::TestCheckSchedulerHeartbeat::test_recent_heartbeat_returns_ok PASSED
test_checks.py::TestCheckSchedulerHeartbeat::test_stale_heartbeat_returns_known_issue PASSED
test_llm_diagnose.py::TestDiagnose::test_no_api_key_returns_unavailable PASSED
test_llm_diagnose.py::TestDiagnose::test_long_logs_truncated_to_50_lines PASSED
test_llm_diagnose.py::TestDiagnose::test_logs_truncated_to_10kb PASSED
test_llm_diagnose.py::TestDiagnose::test_httpx_error_returns_unavailable PASSED
test_llm_diagnose.py::TestDiagnose::test_successful_call_returns_text PASSED

37 passed
```

---

## Task 14: Deploy to VPS

### Step 14a: Build and verify compose config locally

```bash
cd argus
docker compose config
```

Expected: clean YAML output with 4 services.

### Step 14b: Copy guardian/ to VPS

```bash
scp -r argus/guardian/ ubuntu@<VPS_IP>:~/argus/guardian/
scp argus/docker-compose.yml ubuntu@<VPS_IP>:~/argus/docker-compose.yml
```

### Step 14c: Build guardian image on VPS

```bash
ssh ubuntu@<VPS_IP>
cd ~/argus
docker compose build argus-guardian
```

Expected: image builds without error.

### Step 14d: Start guardian

```bash
docker compose up -d argus-guardian
```

### Step 14e: Verify startup logs

```bash
docker compose logs argus-guardian --tail=30
```

Expected log lines:
```
argus-guardian starting
scheduled every 300s
running checks          ← immediate first run
check container_liveness: OK
check queue_runaway: OK
...
```

No `ERROR` lines. No Python tracebacks.

### Step 14f: Verify guardian_state table created in Argus DB

```bash
docker compose exec db psql -U argus -d argus -c "SELECT * FROM guardian_state;"
```

Expected: 1 row with `id=1`, `last_heartbeat_at` populated within ~5 minutes of Argus running.

---

## Acceptance criteria mapping

| Criterion (from spec) | Verified by |
|---|---|
| Guardian runs every 5 min | Task 13 (unit tests) + Task 14e (deploy logs) |
| Container not running → restart + alert | `TestCheckContainerLiveness::test_container_stopped_restarts` |
| Health endpoint fails → restart + alert | `TestCheckContainerLiveness::test_health_500_restarts_app` |
| Queue growing 30min → alert | `TestCheckQueueRunaway::test_growth_over_30min_returns_known_issue` |
| LLM all-failed → alert | `TestCheckLlmRouter::test_all_failed_returns_known_issue` |
| LLM partial degradation → Gemini diagnosis | `TestCheckLlmRouter::test_high_failure_rate_returns_unknown_anomaly` |
| Liq silent + items flowing → alert | `TestCheckLiqSilence::test_old_liq_recent_items_known_issue` |
| Liq silent + no items → Gemini diagnosis | `TestCheckLiqSilence::test_old_liq_old_items_unknown_anomaly` |
| Claims drought → Gemini diagnosis | `TestCheckClaimsDrought::test_near_zero_ratio_returns_unknown_anomaly` |
| Scheduler silent 15min → restart + alert | `TestCheckSchedulerHeartbeat::test_stale_heartbeat_returns_known_issue` |
| Alert cooldowns respected | Implemented in `main.py` `_run_checks()` |
| Gemini called only for UNKNOWN_ANOMALY | Implemented in `main.py` (guarded by `result.status == Status.UNKNOWN_ANOMALY`) |
| guardian_state created on startup | `TestDb::test_init_db_creates_table_and_seeds_row` |
| Heartbeat written by Argus every 5min | Task 12 (`_heartbeat_job`) |
| DB password matches compose (`argus` not `arguspass`) | Task 11 note |

## Out of scope (do not implement)

- Dashboard / metrics history
- Auto-bump of batch_size
- Auto-scaling workers
- Guardian monitoring itself
- Per-provider failure alerting (Gemini 55% fail rate normal with fallback)
- docker-socket-proxy or SSH-based restart
