# Argus Guardian — Design Spec

**Date:** 2026-06-17
**Status:** Approved

## Problem

Argus runs 24/7 on Oracle VPS but has no external watchdog. If the `app` container dies, the internal APScheduler watchdog dies with it — no alert, no restart. Known failure modes (queue runaway, liq-listener silence, LLM provider exhaustion, claims drought) go undetected until manually checked.

## Solution

A lightweight `argus-guardian` container on the same VPS, co-located in `argus/docker-compose.yml`. Checks Argus health every 5 minutes. Sends Telegram alerts. Restarts dead containers. For unknown anomalies only: calls Gemini to diagnose from logs.

## Architecture

**New files:**
- `argus/guardian/main.py` — APScheduler loop, 5-minute interval, entry point
- `argus/guardian/checks.py` — 5 check functions returning CheckResult
- `argus/guardian/llm_diagnose.py` — Gemini call for unknown anomalies
- `argus/guardian/Dockerfile` — Python 3.12-slim, minimal deps
- New service `argus-guardian` in `argus/docker-compose.yml`

**Access:**
- Docker socket (`/var/run/docker.sock`) — read container status + restart
- Argus DB (`postgresql://argus:...@db:5432/argus`) — queue metrics, claims, llm_calls
- Argus health API (`http://app:8080/health`) — liveness check
- Telegram (same `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as Argus)
- Gemini free (same `GEMINI_API_KEY`) — only for LLM diagnosis path

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
    message: str           # human-readable for Telegram
    remediation: str | None  # action taken, or None
    logs_snippet: str | None  # for LLM diagnosis, or None
```

## 5 Checks

### 1. Container liveness

- Query Docker socket for `app` and `liq-listener` containers
- If container status != `running` OR `http://app:8080/health` returns non-200: `KNOWN_ISSUE`
- Remediation: `docker restart <container_name>`
- Telegram: "⚠️ argus-guardian: restarted {name} (was {status})"
- Cooldown: 30 minutes (don't restart loop if already restarted recently)

### 2. Queue runaway

- Query: `SELECT count(*) FROM llm_queue WHERE status='pending'`
- Compare to `guardian_state.last_queue_depth`
- `KNOWN_ISSUE` if: depth > 150 OR (delta > 8 for 2 consecutive runs)
- Remediation: **none** (alert-only — auto-bump batch_size is premature until first real queue runaway is observed)
- Telegram: "📬 argus-guardian: llm_queue {depth} pending (delta +{delta}). Check llm_batch job."
- Cooldown: 2 hours

### 3. LLM router blocked

- Query: `SELECT count(*) FROM llm_calls WHERE ts > now() - interval '1 hour' AND ok = false`
- `KNOWN_ISSUE` if: failed_count >= 3 AND ok_count = 0 in last hour (all providers failing)
- `UNKNOWN_ANOMALY` if: high failure rate with some successes (partial degradation)
- Remediation: none
- Telegram (KNOWN): "🔴 argus-guardian: LLM router all-failed ({n} errors/1h). Providers exhausted."
- Telegram (UNKNOWN): calls llm_diagnose with last 50 lines of app logs
- Cooldown: 2 hours

### 4. Liq-listener silence

- Query: `SELECT max(ts) FROM liquidations`
- `KNOWN_ISSUE` if: last liquidation > 6h ago
- Cross-check: query `SELECT max(ts) FROM items WHERE source_id IN (SELECT id FROM sources WHERE kind='hyperliquid')` — if hyperliquid job ran recently (< 30min), market is just quiet → suppress alert
- `UNKNOWN_ANOMALY` if: silence AND hyperliquid job seems stuck
- Telegram: "📡 argus-guardian: liq-listener silent 6h+. Check HL WebSocket."
- Cooldown: 6 hours

### 5. Claims drought

- Query: `SELECT count(*) FROM claims WHERE entry_ts > now() - interval '12 hours'`
- Cross-check: `SELECT count(*) FROM llm_queue WHERE status='done' AND processed_at > now() - interval '12 hours'` — if queue draining but 0 claims: `UNKNOWN_ANOMALY` (extractor broken); if queue empty too: `OK` (no input, normal)
- `UNKNOWN_ANOMALY` if: 0 claims AND queue was drained (items processed but no claims extracted)
- Telegram: calls llm_diagnose with last 50 lines of app logs
- Cooldown: 12 hours

## State persistence: `guardian_state` table

```sql
CREATE TABLE guardian_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_queue_depth INTEGER DEFAULT 0,
    last_queue_delta_positive BOOLEAN DEFAULT FALSE,
    last_alert_container TIMESTAMPTZ,
    last_alert_queue TIMESTAMPTZ,
    last_alert_llm TIMESTAMPTZ,
    last_alert_liq TIMESTAMPTZ,
    last_alert_claims TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT now()
);
-- Seed one row on startup: INSERT INTO guardian_state(id) VALUES(1) ON CONFLICT DO NOTHING;
```

Auto-created by `Base.metadata.create_all()` in guardian startup (reuses Argus DB, same engine).

## LLM diagnosis (llm_diagnose.py)

Called only for `UNKNOWN_ANOMALY`. Never called for `KNOWN_ISSUE` or `OK`.

```python
def diagnose(anomaly_type: str, logs_snippet: str) -> str:
    """Call Gemini free, return short diagnosis string for Telegram."""
    prompt = f"Argus agent anomaly: {anomaly_type}\n\nRecent logs:\n{logs_snippet}\n\nWhat likely caused this? Answer in 2-3 sentences max."
    # httpx POST to Gemini v1beta generateContent
    # Returns diagnosis string or "LLM diagnosis unavailable" on error
```

Guardian never acts on LLM output — it is appended to the Telegram alert only.

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

Note: Docker socket is mounted **without** `:ro` because container restart requires write access to the socket. This is a deliberate security trade-off: the guardian container has no outbound internet except Telegram and Gemini APIs, and runs on a single-tenant VPS.

## Out of scope

- Dashboard / metrics history
- Auto-bump of batch_size (revisit when first real queue runaway is observed)
- Auto-scaling workers
- Guardian monitoring itself (blind spot — acceptable)
- Alerting on individual provider failures (Gemini 55% fail rate is normal with fallback)

## Dependencies

- `docker>=7.0` — Docker SDK for Python (container status + restart)
- `psycopg2-binary` — DB access (reuses Argus DB, same schema)
- `sqlalchemy` — ORM for guardian_state table
- `httpx` — Gemini API call
- `apscheduler>=3.10` — 5-minute check loop
