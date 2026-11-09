"""
RAG System — System Routes
Health check, stats.
"""

import time
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from config import settings
from core.database import Document, DocumentChunk, ChatSession, ChatMessage, ProcessingTask, User, get_db

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "rag-api"}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    docs = await db.execute(select(func.count(Document.id)))
    chunks = await db.execute(select(func.count(DocumentChunk.id)))
    chats = await db.execute(select(func.count(ChatSession.id)))
    messages = await db.execute(select(func.count(ChatMessage.id)))

    docs_by_status = await db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    )

    return {
        "documents": docs.scalar_one(),
        "chunks": chunks.scalar_one(),
        "chat_sessions": chats.scalar_one(),
        "chat_messages": messages.scalar_one(),
        "documents_by_status": {row[0]: row[1] for row in docs_by_status.all()},
    }


@router.get("/monitor")
async def monitor(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full system monitor: stats + active tasks + service health."""
    import httpx
    import redis.asyncio as aioredis

    # --- Stats ---
    docs = (await db.execute(select(func.count(Document.id)))).scalar_one()
    chunks = (await db.execute(select(func.count(DocumentChunk.id)))).scalar_one()
    chats = (await db.execute(select(func.count(ChatSession.id)))).scalar_one()
    messages = (await db.execute(select(func.count(ChatMessage.id)))).scalar_one()

    docs_by_type = (await db.execute(
        select(Document.source_type, func.count(Document.id)).group_by(Document.source_type)
    )).all()

    # --- Active tasks ---
    active_tasks_q = await db.execute(
        select(ProcessingTask, Document.filename)
        .join(Document, Document.id == ProcessingTask.document_id)
        .where(ProcessingTask.status.in_(["pending", "running"]))
        .order_by(ProcessingTask.created_at.desc())
        .limit(20)
    )
    active_tasks = [
        {
            "id": t.id,
            "document": filename[:60],
            "task_type": t.task_type,
            "status": t.status,
            "progress": t.progress,
            "error": t.error_message,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t, filename in active_tasks_q.all()
    ]

    # --- Recent completed/failed tasks ---
    recent_q = await db.execute(
        select(ProcessingTask, Document.filename)
        .join(Document, Document.id == ProcessingTask.document_id)
        .where(ProcessingTask.status.in_(["completed", "failed"]))
        .order_by(ProcessingTask.completed_at.desc().nullslast())
        .limit(10)
    )
    recent_tasks = [
        {
            "id": t.id,
            "document": filename[:60],
            "task_type": t.task_type,
            "status": t.status,
            "progress": t.progress,
            "error": t.error_message,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t, filename in recent_q.all()
    ]

    # --- Service health ---
    health = {}

    # DB
    try:
        await db.execute(text("SELECT 1"))
        health["database"] = {"ok": True, "name": "PostgreSQL + pgvector"}
    except Exception as e:
        health["database"] = {"ok": False, "error": str(e)}

    # Redis
    try:
        r = aioredis.from_url(settings.redis.url)
        await r.ping()
        await r.aclose()
        health["redis"] = {"ok": True, "name": "Redis"}
    except Exception as e:
        health["redis"] = {"ok": False, "error": str(e)}

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            t0 = time.monotonic()
            resp = await client.get(f"{settings.ai.ollama_url}/api/tags")
            latency = round((time.monotonic() - t0) * 1000)
            models = [m["name"] for m in resp.json().get("models", [])]
            health["ollama"] = {"ok": True, "name": "Ollama", "latency_ms": latency, "models": models}
    except Exception as e:
        health["ollama"] = {"ok": False, "error": str(e)}

    return {
        "stats": {
            "documents": docs,
            "chunks": chunks,
            "chat_sessions": chats,
            "messages": messages,
            "by_source": {row[0]: row[1] for row in docs_by_type},
        },
        "active_tasks": active_tasks,
        "recent_tasks": recent_tasks,
        "services": health,
    }


@router.get("/quality")
async def quality_metrics(
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get retrieval quality metrics summary."""
    from services.ranker_agent import RankerAgent
    agent = RankerAgent()
    summary = await agent.get_quality_summary(db, hours=hours)
    degradation = await agent.check_degradation(db)
    return {"summary": summary, "degradation": degradation}


@router.post("/sync/youtube")
async def trigger_youtube_sync(
    user: User = Depends(get_current_user),
):
    """Trigger YouTube transcript sync from n8n DB → RAG DB (async Celery task)."""
    from tasks.youtube_sync_task import sync_youtube_transcripts
    result = sync_youtube_transcripts.delay(user_id=user.id)
    return {"task_id": result.id, "status": "queued"}
