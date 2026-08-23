from datetime import datetime, timedelta
import logging

from tresrv import repo
from tresrv.bot.meals import build_meal_fields
from tresrv.llm import NotFoodError, ParseError

logger = logging.getLogger("tresrv.scheduler")

_BACKOFF_SCHEDULE = [60, 120, 300]


def next_backoff_seconds(attempts: int) -> int:
    if attempts < len(_BACKOFF_SCHEDULE):
        return _BACKOFF_SCHEDULE[attempts]
    return _BACKOFF_SCHEDULE[-1]


def drain_pending_parse(session, llm_client, now: datetime, max_attempts: int) -> dict:
    counts = {"resolved": 0, "retried": 0, "failed_permanently": 0}

    for pending in repo.fetch_due_pending(session, now):
        try:
            if pending.raw_input_type == "text":
                parsed = llm_client.parse_text(pending.raw_text)
            else:
                parsed = llm_client.parse_photo(pending.storage_path)
        except NotFoodError:
            repo.mark_pending_failed_permanently(session, pending, "not_food")
            counts["failed_permanently"] += 1
            continue
        except ParseError as exc:
            repeated_parse_error = (pending.last_error is not None and pending.attempts >= 1)
            if repeated_parse_error or pending.attempts + 1 >= max_attempts:
                repo.mark_pending_failed_permanently(session, pending, str(exc))
                counts["failed_permanently"] += 1
            else:
                next_attempt_at = now + timedelta(seconds=next_backoff_seconds(pending.attempts))
                repo.mark_pending_retry(session, pending, str(exc), next_attempt_at)
                counts["retried"] += 1
            continue

        fields = build_meal_fields(
            chat_id=pending.chat_id, parsed=parsed, raw_input_type=pending.raw_input_type,
            raw_text=pending.raw_text, storage_path=pending.storage_path,
            telegram_file_id=pending.telegram_file_id, logged_at=pending.logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        meal = repo.save_meal(session, **fields)
        repo.mark_pending_resolved(session, pending, meal.id)
        counts["resolved"] += 1

    return counts


def run_pending_parse_drain_job(session_factory, llm_client, max_attempts: int) -> None:
    from datetime import timezone
    session = session_factory()
    try:
        counts = drain_pending_parse(session, llm_client, datetime.now(timezone.utc), max_attempts)
        if counts["resolved"] or counts["retried"] or counts["failed_permanently"]:
            logger.info("pending_parse drain: %s", counts)
    finally:
        session.close()


def run_heartbeat_job(session_factory) -> None:
    from datetime import timezone
    from sqlalchemy import text
    session = session_factory()
    try:
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY, last_beat_at TIMESTAMP)"
        ))
        session.execute(text(
            "INSERT INTO heartbeat (id, last_beat_at) VALUES (1, :now) "
            "ON CONFLICT (id) DO UPDATE SET last_beat_at = :now"
        ), {"now": datetime.now(timezone.utc)})
        session.commit()
    finally:
        session.close()
