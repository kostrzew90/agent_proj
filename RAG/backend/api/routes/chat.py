from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from api.deps import get_current_user
from api.rate_limit import limiter
from core.database import get_db, User, ChatSession
from services.chat_service import ChatService

router = APIRouter()
service = ChatService()


async def _owned_chat(db: AsyncSession, chat_id: int, user_id: int) -> ChatSession:
    """Load a chat session, 404 unless it belongs to this user.
    Without this, chat_id alone granted access to any user's conversation."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == chat_id, ChatSession.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return session


class CreateChatRequest(BaseModel):
    title: Optional[str] = None
    folder_ids: list[int] = []
    tag_ids: list[int] = []
    document_ids: list[int] = []


class ChatQueryRequest(BaseModel):
    query: str


@router.post("/")
async def create_chat_session(
    request: CreateChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Context must be the caller's own — otherwise the chat silently retrieves
    # nothing (retrieval is user-scoped) and the user never learns why.
    from core.database import Document, Folder, Tag
    for model, ids, label in (
        (Folder, request.folder_ids, "Folder"),
        (Tag, request.tag_ids, "Tag"),
        (Document, request.document_ids, "Document"),
    ):
        if not ids:
            continue
        owned = await db.execute(
            select(model.id).where(model.id.in_(ids), model.user_id == user.id)
        )
        if set(owned.scalars().all()) != set(ids):
            raise HTTPException(status_code=404, detail=f"{label} not found")

    session = await service.create_session(
        db,
        user_id=user.id,
        title=request.title,
        folder_ids=request.folder_ids,
        tag_ids=request.tag_ids,
        document_ids=request.document_ids,
    )
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
    }


@router.post("/{chat_id}/query")
@limiter.limit("20/minute")
async def query_chat(
    chat_id: int,
    request: Request,
    body: ChatQueryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _owned_chat(db, chat_id, user.id)

    async def _stream():
        async for chunk in service.query_stream(db, chat_id, user.id, body.query):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{chat_id}/history")
async def get_chat_history(
    chat_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _owned_chat(db, chat_id, user.id)
    messages = await service.get_full_history(db, chat_id)
    return {
        "chat_id": chat_id,
        "messages": messages,
    }


@router.get("/")
async def list_chat_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from core.database import ChatSession, ChatMessage
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at,
                "message_count": len(s.messages) if s.messages else 0,
            }
            for s in sessions
        ]
    }


@router.delete("/{chat_id}")
async def delete_chat_session(
    chat_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _owned_chat(db, chat_id, user.id)
    await service.delete_session(db, chat_id)
    return {"ok": True}
