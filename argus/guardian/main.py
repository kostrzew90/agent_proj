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
