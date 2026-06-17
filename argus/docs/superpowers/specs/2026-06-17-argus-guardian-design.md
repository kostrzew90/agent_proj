# Argus Guardian — Design Spec

**Date:** 2026-06-17  
**Status:** Approved (rev 2 — user review incorporated)

## Problem

Argus runs 24/7 on Oracle VPS but has no external watchdog. If the `app` container dies, the internal APScheduler watchdog dies with it — no alert, no restart. Known failure modes (queue runaway, liq-listener silence, LLM provider exhaustion, claims drought, silent scheduler death) go undetected until manually checked.

## Solution

A lightweight `argus-guardian` container on the same VPS, co-located in `argus/docker-compose.yml`. Checks Argus health every 5 minutes. Sends Telegram alerts. Restarts dead containers. For unknown anomalies only: calls Gemini to diagnose from logs.

## Architecture

**New files:**
- `argus/guardian/main.py` — APScheduler loop, 5-minute interval, entry point
- `argus/guardian/checks.py` — 6 check functions returning CheckResult
- `argus/guardian/llm_diagnose.py` — Gemini call for unknown anomalies
- `argus/guardian/Dockerfile` — Python 3.12-slim, minimal deps
- New service `argus-guardian` in `argus/docker-compose.yml`

**Small change to Argus itself:**
- `argus/argus/main.py` — add `_heartbeat_job` (APScheduler, every 5 min) writing `now()` to `guardian_state.last_heartbeat_at` in Argus DB. This is the scheduler liveness signal.

**Access:**
- Docker socket (`/var/run/docker.sock`) — read container status + restart
- Argus DB (`postgresql://argus:arguspass@db:5432/argus`) — queue metrics, claims, llm_calls, guardian_state
- Argus health API (`http://app:8080/health`) — liveness + payload check
- Telegram (same `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as Argus)
- Gemini free (same `GEMINI_API_KEY`) — only for LLM diagnosis path

**Note on Docker socket security:** `/var/run/docker.sock` gives the container near-root access on the host. This is a deliberate trade-off acceptable on a single-tenant VPS. Alternatives (docker-socket-proxy, SSH-based restart) are out of scope. The guardian container has no other outbound internet besides Telegram and Gemini APIs.

## CheckResult type

```python
from dataclasses import dataclass
from enum import Enum

class Status(Enum):
    OK = "ok"
    KNOWN_ISSUE = "known_issue"
    UNKNOWN_ANOMALY = "unknown_anomaly"

@dataclass
class CheckResult:
    name: str
    status: Status
    message: str            # human-readable for Telegram
    remediation: str | None # action taken, or None
    logs_snippet: str | None  # for LLM diagnosis, or None
```

## 6 Checks

### 1. Container liveness

Three-stage check (in order):

1. Container status == `running` via Docker socket
2. `GET http://app:8080/health` returns HTTP 200
3. Response payload contains `{"status": "ok"}` (and optionally `"db": "ok"`, `"scheduler": "ok"` if Argus exposes them)

`KNOWN_ISSUE` if any stage fails.

- Remediation: `docker restart <container_name>` for `app` and `liq-listener`
- Telegram: "⚠️ argus-guardian: restarted {name} (stage failed: {stage})"
- Cooldown: 30 minutes (prevent restart loop)

### 2. Queue runaway

Growth-rate based, not absolute threshold:

- Every run: record `(timestamp, depth)` in `guardian_state`
- `KNOWN_ISSUE` if queue has grown monotonically for **30 minutes** (6 consecutive 5-min checks with positive delta, no decrease)
- This avoids false positives from short bursts (initial backfill, one-time feed spike)
- Remediation: **none** (alert-only — auto-bump batch_size premature until first real runaway observed)
- Telegram: "📬 argus-guardian: llm_queue growing 30min+ (now {depth}, started {depth_30min_ago}). Check llm_batch job."
- Cooldown: 2 hours

### 3. LLM router blocked

```sql
SELECT
  count(*) FILTER (WHERE ok = true)  AS ok_count,
  count(*) FILTER (WHERE ok = false) AS failed_count,
  count(*) AS total_calls
FROM llm_calls
WHERE ts > now() - interval '1 hour'
```

- `KNOWN_ISSUE` if: `total_calls >= 3` AND `ok_count = 0` (all-failed, not just no traffic)
- `UNKNOWN_ANOMALY` if: `total_calls >= 3` AND failure rate > 80% but `ok_count > 0` (partial degradation)
- Suppress if `total_calls < 3` (insufficient data — could be quiet hour)
- Remediation: none
- Telegram (KNOWN): "🔴 argus-guardian: LLM all-failed ({failed_count} errors/1h, 0 success). Providers exhausted."
- Telegram (UNKNOWN): calls `llm_diagnose` with last 50 lines of app logs
- Cooldown: 2 hours

### 4. Liq-listener silence

Two-signal cross-check for faster diagnostics:

```sql
-- Signal A: last liquidation
SELECT max(ts) FROM liquidations;

-- Signal B: last item ingested (any source)
SELECT max(fetched_at) FROM items;
```

| Signal A | Signal B | Diagnosis |
|---|---|---|
| < 6h ago | any | OK — market just quiet |
| > 6h ago | < 30min ago | `KNOWN_ISSUE` — items flowing, liq-listener dead |
| > 6h ago | > 6h ago | `UNKNOWN_ANOMALY` — nothing ingesting, broader outage |

- Telegram (KNOWN): "📡 argus-guardian: liq-listener silent 6h+ (items still flowing). Check HL WebSocket."
- Telegram (UNKNOWN): calls `llm_diagnose`
- Cooldown: 6 hours

### 5. Claims drought

Rate-based, not binary zero check:

```sql
SELECT
  count(*) AS claims_12h
FROM claims
WHERE entry_ts > now() - interval '12 hours';

SELECT
  count(*) AS processed_12h
FROM llm_queue
WHERE status = 'done' AND processed_at > now() - interval '12 hours';
```

- Compute `claims_per_processed = claims_12h / processed_12h` (if `processed_12h > 0`)
- `UNKNOWN_ANOMALY` if: `processed_12h > 5` AND `claims_per_processed < 0.05` (normal ratio ~0.06–0.10; near-zero means extractor degraded)
- `OK` if: `processed_12h == 0` (queue empty — no input, not a failure)
- Telegram: calls `llm_diagnose` with last 50 lines of app logs
- Cooldown: 12 hours

### 6. Scheduler heartbeat (new)

Most common silent failure: container running, health OK, scheduler dead — nothing executes.

**In Argus:** add `_heartbeat_job` to APScheduler in `main.py` (every 5 min):
```python
def _heartbeat_job():
    with SessionLocal() as s:
        s.execute(text(
            "UPDATE guardian_state SET last_heartbeat_at = now() WHERE id = 1"
        ))
        s.commit()
```

**In Guardian:** check `guardian_state.last_heartbeat_at`:
- `KNOWN_ISSUE` if `last_heartbeat_at < now() - 15 minutes` AND container is `running`
- (if container is not running, Check #1 already covers it)
- Remediation: `docker restart app` (scheduler may be hung)
- Telegram: "💀 argus-guardian: Argus scheduler silent 15min+ (container running). Restarting."
- Cooldown: 30 minutes

## State persistence: `guardian_state` table

Created by guardian on startup via raw SQL (`psycopg2`, no SQLAlchemy — 1 table, 5 queries, no ORM needed):

```sql
CREATE TABLE IF NOT EXISTS guardian_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    -- Queue tracking
    last_queue_depth INTEGER DEFAULT 0,
    last_queue_growth_start TIMESTAMPTZ,   -- when monotonic growth began
    -- Alert cooldowns
    last_alert_container TIMESTAMPTZ,
    last_alert_queue TIMESTAMPTZ,
    last_alert_llm TIMESTAMPTZ,
    last_alert_liq TIMESTAMPTZ,
    last_alert_claims TIMESTAMPTZ,
    last_alert_heartbeat TIMESTAMPTZ,
    -- Heartbeat (written by Argus _heartbeat_job)
    last_heartbeat_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT now()
);
INSERT INTO guardian_state(id) VALUES(1) ON CONFLICT DO NOTHING;
```

## LLM diagnosis (llm_diagnose.py)

Called only for `UNKNOWN_ANOMALY`. Never for `KNOWN_ISSUE` or `OK`. Guardian never acts on LLM output — diagnosis is appended to Telegram alert only.

```python
def diagnose(anomaly_type: str, logs_snippet: str) -> str:
    """Call Gemini free, return 2-3 sentence diagnosis for Telegram."""
    # Truncate logs to last 50 lines, max 10KB
    lines = logs_snippet.splitlines()[-50:]
    truncated = "\n".join(lines)[-10_000:]
    prompt = (
        f"Argus agent anomaly: {anomaly_type}\n\n"
        f"Recent logs:\n{truncated}\n\n"
        "What likely caused this? Answer in 2-3 sentences max."
    )
    # httpx POST to Gemini v1beta generateContent
    # Returns diagnosis string or "LLM diagnosis unavailable" on error
```

## docker-compose.yml addition

```yaml
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
    ARGUS_DB_URL: postgresql://argus:arguspass@db:5432/argus
    TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
    TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
    GEMINI_API_KEY: ${GEMINI_API_KEY}
    GEMINI_MODEL: ${ARGUS_GEMINI_MODEL:-gemini-2.5-flash}
    CHECK_INTERVAL_SECONDS: "300"
  networks:
    - argus-net
```

## Out of scope

- Dashboard / metrics history
- Auto-bump of batch_size (revisit when first real queue runaway observed)
- Auto-scaling workers
- Guardian monitoring itself (blind spot — acceptable)
- Alerting on individual provider failures (Gemini 55% fail rate is normal with fallback)
- docker-socket-proxy or SSH-based restart (overkill for single-tenant VPS)

## Dependencies (guardian only)

- `psycopg2-binary` — DB access (raw SQL, no ORM)
- `docker>=7.0` — Docker SDK for Python (container status + restart)
- `httpx` — Gemini API call + Argus health check
- `apscheduler>=3.10` — 5-minute check loop
