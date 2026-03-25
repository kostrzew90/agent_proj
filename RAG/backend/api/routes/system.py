"""
RAG System — System Routes
Health check, stats.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Document, DocumentChunk, ChatSession, ChatMessage, get_db

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "rag-api"}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
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
