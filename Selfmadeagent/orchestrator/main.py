from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncpg
import asyncio
import json
import logging
import os
import uuid

from monitoring.langfuse_setup import init_langfuse, flush_langfuse
from agent.sessions import create_session, get_session, list_sessions, end_session, get_pool
from agent.loop import agent_step, _get_episodic, _working_memories
from memory.reflection import ReflectionEngine

logger = logging.getLogger(__name__)
DB_URL = os.getenv("AGENT_DB_URL", "postgresql://agent:agentpass@agent-db:5432/agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_langfuse()
    await get_pool()
    yield
    flush_langfuse()


app = FastAPI(title="Selfmadeagent Orchestrator", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "service": "orchestrator", "db": "connected" if db_ok else "unreachable"}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.session_id:
        session = await get_session(req.session_id)
        if not session:
            session = await create_session(goal=req.message)
    else:
        session = await create_session(goal=req.message)
    response_text = await agent_step(session, req.message)
    return ChatResponse(session_id=session.id, response=response_text)


@app.get("/sessions")
async def sessions_list():
    return await list_sessions()


@app.post("/sessions/{session_id}/end")
async def session_end(session_id: str):
    """End session and trigger reflection."""
    try:
        episodic = await _get_episodic()
        engine = ReflectionEngine(episodic=episodic)
        asyncio.create_task(_run_reflection(engine, session_id))
    except Exception:
        pass

    await end_session(session_id)
    _working_memories.pop(session_id, None)
    return {"status": "ended"}


async def _run_reflection(engine: ReflectionEngine, session_id: str):
    """Background reflection task."""
    try:
        result = await engine.reflect_on_session(session_id)
        logger.info(f"Reflection for {session_id}: {len(result.patterns)} patterns extracted")
    except Exception as e:
        logger.error(f"Reflection failed for {session_id}: {e}")


# --- Memory API endpoints ---

@app.get("/api/memory/patterns")
async def get_patterns():
    """List all learned patterns."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, pattern, solution, confidence, times_applied, times_failed, "
            "needs_review, verified, verified_by, source FROM learned_patterns ORDER BY confidence DESC"
        )
    return [dict(r) for r in rows]


@app.post("/api/memory/patterns/{pattern_id}/review")
async def review_pattern(pattern_id: int, action: str = "approve"):
    """Approve or reject a needs_review pattern."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if action == "approve":
            await conn.execute(
                "UPDATE learned_patterns SET needs_review = FALSE, verified = TRUE, "
                "verified_by = 'user', verified_at = NOW(), review_result = 'approved' WHERE id = $1",
                pattern_id,
            )
        else:
            await conn.execute(
                "UPDATE learned_patterns SET needs_review = FALSE, review_result = 'rejected', "
                "confidence = confidence * 0.3 WHERE id = $1",
                pattern_id,
            )
    return {"status": action, "pattern_id": pattern_id}


@app.get("/api/memory/facts")
async def get_facts():
    """List all project memory facts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM project_memory ORDER BY key")
    return [dict(r) for r in rows]


@app.get("/api/sessions/{session_id}/trace")
async def get_trace(session_id: str):
    """Get action timeline for a session."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, event_type, content, outcome, ts FROM episodes "
            "WHERE session_id = $1 ORDER BY ts",
            uuid.UUID(session_id),
        )
    return [dict(r) for r in rows]


# --- WebSocket ---

@app.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = await get_session(session_id)
    if not session:
        session = await create_session(goal=None)
        await websocket.send_json({"type": "session_created", "session_id": session.id})

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_message = msg.get("message", "")
            if not user_message:
                continue
            response_text = await agent_step(session, user_message)
            await websocket.send_json({"type": "response", "content": response_text, "session_id": session.id})
    except WebSocketDisconnect:
        # Trigger reflection on disconnect
        try:
            episodic = await _get_episodic()
            engine = ReflectionEngine(episodic=episodic)
            asyncio.create_task(_run_reflection(engine, session.id))
        except Exception:
            pass
        await end_session(session.id, summary="WebSocket disconnected")
        _working_memories.pop(session.id, None)
