"""Monitoring routes — retrieval stats, LLM usage, indexing history, errors."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter()

LAST_24H = "AND ts >= NOW() - INTERVAL '24 hours'"
LAST_24H_CREATED = "AND created_at >= NOW() - INTERVAL '24 hours'"


class RetrievalStats(BaseModel):
    query_count: int = 0
    avg_latency_ms: float | None = None
    avg_embedding_ms: float | None = None
    avg_semantic_count: float | None = None
    avg_keyword_count: float | None = None
    avg_final_count: float | None = None


class LLMStats(BaseModel):
    call_count: int = 0
    avg_latency_ms: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    success_rate: float | None = None
    by_provider: list[dict] = []


class IndexingJobItem(BaseModel):
    id: int
    repo_id: str
    started_at: str
    finished_at: str | None = None
    files_scanned: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    chunks_created: int = 0
    symbols_found: int = 0
    duration_ms: float | None = None
    status: str = "running"


class ErrorSummary(BaseModel):
    top_signatures: list[dict] = []
    recent: list[dict] = []


class MonitoringOverview(BaseModel):
    retrieval: RetrievalStats
    llm: LLMStats
    recent_indexing: list[IndexingJobItem]
    errors: ErrorSummary


@router.get("/retrieval-stats", response_model=RetrievalStats)
def retrieval_stats(request: Request):
    """Retrieval performance stats over last 24h."""
    db = request.app.state.db
    with db.get_session() as session:
        row = session.execute(text(f"""
            SELECT
                COUNT(*) AS cnt,
                AVG(latency_ms) AS avg_lat,
                AVG(embedding_ms) AS avg_emb,
                AVG(semantic_count) AS avg_sem,
                AVG(keyword_count) AS avg_kw,
                AVG(final_count) AS avg_fin
            FROM retrieval_logs
            WHERE TRUE {LAST_24H_CREATED}
        """)).fetchone()
        return RetrievalStats(
            query_count=row[0] or 0,
            avg_latency_ms=round(row[1], 2) if row[1] else None,
            avg_embedding_ms=round(row[2], 2) if row[2] else None,
            avg_semantic_count=round(row[3], 1) if row[3] else None,
            avg_keyword_count=round(row[4], 1) if row[4] else None,
            avg_final_count=round(row[5], 1) if row[5] else None,
        )


@router.get("/llm-stats", response_model=LLMStats)
def llm_stats(request: Request):
    """LLM call statistics over last 24h."""
    db = request.app.state.db
    with db.get_session() as session:
        row = session.execute(text(f"""
            SELECT
                COUNT(*) AS cnt,
                AVG(latency_ms) AS avg_lat,
                COALESCE(SUM(input_tokens), 0) AS total_in,
                COALESCE(SUM(output_tokens), 0) AS total_out,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
            FROM llm_calls
            WHERE TRUE {LAST_24H.replace('ts', 'ts')}
        """)).fetchone()

        providers = session.execute(text(f"""
            SELECT provider, model, COUNT(*) AS cnt,
                   AVG(latency_ms) AS avg_lat
            FROM llm_calls
            WHERE TRUE {LAST_24H}
            GROUP BY provider, model
            ORDER BY cnt DESC
        """)).fetchall()

        return LLMStats(
            call_count=row[0] or 0,
            avg_latency_ms=round(row[1], 2) if row[1] else None,
            total_input_tokens=int(row[2]),
            total_output_tokens=int(row[3]),
            success_rate=round(row[4], 4) if row[4] is not None else None,
            by_provider=[
                {"provider": p[0], "model": p[1], "count": p[2],
                 "avg_latency_ms": round(p[3], 2) if p[3] else None}
                for p in providers
            ],
        )


@router.get("/indexing-history", response_model=list[IndexingJobItem])
def indexing_history(request: Request, limit: int = 10):
    """Recent indexing jobs."""
    db = request.app.state.db
    with db.get_session() as session:
        rows = session.execute(text("""
            SELECT id, repo_id, started_at, finished_at,
                   files_scanned, files_indexed, files_skipped, files_errored,
                   chunks_created, symbols_found, duration_ms, status
            FROM indexing_jobs
            ORDER BY started_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        return [
            IndexingJobItem(
                id=r[0], repo_id=r[1],
                started_at=r[2].isoformat() if r[2] else "",
                finished_at=r[3].isoformat() if r[3] else None,
                files_scanned=r[4] or 0, files_indexed=r[5] or 0,
                files_skipped=r[6] or 0, files_errored=r[7] or 0,
                chunks_created=r[8] or 0, symbols_found=r[9] or 0,
                duration_ms=r[10], status=r[11] or "unknown",
            )
            for r in rows
        ]


@router.get("/errors", response_model=ErrorSummary)
def errors(request: Request):
    """Top error signatures + recent errors from last 24h."""
    db = request.app.state.db
    with db.get_session() as session:
        top = session.execute(text(f"""
            SELECT error_signature, COUNT(*) AS cnt, MAX(ts) AS last_seen
            FROM log_events
            WHERE level IN ('error', 'warning')
              AND error_signature IS NOT NULL
              {LAST_24H}
            GROUP BY error_signature
            ORDER BY cnt DESC
            LIMIT 10
        """)).fetchall()

        recent = session.execute(text(f"""
            SELECT ts, service, level, message, error_signature
            FROM log_events
            WHERE level IN ('error', 'warning')
              {LAST_24H}
            ORDER BY ts DESC
            LIMIT 20
        """)).fetchall()

        return ErrorSummary(
            top_signatures=[
                {"signature": r[0], "count": r[1],
                 "last_seen": r[2].isoformat() if r[2] else None}
                for r in top
            ],
            recent=[
                {"ts": r[0].isoformat() if r[0] else None,
                 "service": r[1], "level": r[2],
                 "message": r[3], "signature": r[4]}
                for r in recent
            ],
        )


@router.get("/overview", response_model=MonitoringOverview)
def overview(request: Request):
    """Aggregated monitoring overview — single call for dashboard."""
    return MonitoringOverview(
        retrieval=retrieval_stats(request),
        llm=llm_stats(request),
        recent_indexing=indexing_history(request, limit=5),
        errors=errors(request),
    )
