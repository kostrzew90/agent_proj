import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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
