"""Metrics helper — thin wrappers for inserting monitoring data into DB."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def emit_event(
    db,
    service: str,
    level: str,
    message: str,
    signature: Optional[str] = None,
    meta: Optional[dict] = None,
):
    """Insert a log_events row. Silently ignores failures."""
    try:
        from ai_repo.core.database import LogEvent

        with db.get_session() as session:
            event = LogEvent(
                service=service,
                level=level,
                message=message,
                error_signature=signature,
                meta_json=meta or {},
            )
            session.add(event)
            session.commit()
    except Exception as e:
        logger.debug(f"emit_event failed: {e}")


def record_llm_call(
    db,
    provider: str,
    model: str,
    purpose: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    latency_ms: Optional[float] = None,
    success: bool = True,
    error_msg: Optional[str] = None,
):
    """Insert a llm_calls row."""
    try:
        from ai_repo.core.database import LLMCall

        with db.get_session() as session:
            call = LLMCall(
                provider=provider,
                model=model,
                purpose=purpose,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                success=success,
                error_message=error_msg,
            )
            session.add(call)
            session.commit()
    except Exception as e:
        logger.debug(f"record_llm_call failed: {e}")


def start_indexing_job(db, repo_id: str = "default") -> Optional[int]:
    """Insert a running indexing_jobs row, return job_id."""
    try:
        from ai_repo.core.database import IndexingJob

        with db.get_session() as session:
            job = IndexingJob(repo_id=repo_id, status="running")
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id
    except Exception as e:
        logger.debug(f"start_indexing_job failed: {e}")
        return None


def finish_indexing_job(
    db,
    job_id: int,
    stats: dict,
    status: str = "completed",
):
    """Update an indexing_jobs row with final counters."""
    try:
        from ai_repo.core.database import IndexingJob

        with db.get_session() as session:
            job = session.query(IndexingJob).get(job_id)
            if not job:
                return
            now = datetime.now(timezone.utc)
            job.finished_at = now
            job.files_scanned = stats.get("scanned", 0)
            job.files_indexed = stats.get("indexed", 0)
            job.files_skipped = stats.get("skipped", 0)
            job.files_errored = stats.get("errors", 0)
            job.chunks_created = stats.get("chunks_created", 0)
            job.symbols_found = stats.get("symbols_found", 0)
            job.duration_ms = stats.get("duration_ms")
            job.status = status
            session.commit()
    except Exception as e:
        logger.debug(f"finish_indexing_job failed: {e}")
