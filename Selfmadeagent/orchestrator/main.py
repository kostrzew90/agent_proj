from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncpg
import json
import os

from monitoring.langfuse_setup import init_langfuse, flush_langfuse
from agent.sessions import create_session, get_session, list_sessions, end_session, get_pool
from agent.loop import agent_step

DB_URL = os.getenv("AGENT_DB_URL", "postgresql://agent:agentpass@agent-db:5432/agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init Langfuse + DB pool. Shutdown: flush + close."""
    init_langfuse()
    await get_pool()  # warm up connection pool
    yield
    flush_langfuse()


app = FastAPI(title="Selfmadeagent Orchestrator", lifespan=lifespan)


# --- Health ---

@app.get("/health")
async def health():
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "orchestrator",
        "db": "connected" if db_ok else "unreachable",
    }


# --- REST API ---

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the agent. Creates a session if none provided."""
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
    await end_session(session_id)
    return {"status": "ended"}


# --- WebSocket ---

@app.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for streaming chat."""
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

            await websocket.send_json({
                "type": "response",
                "content": response_text,
                "session_id": session.id,
            })
    except WebSocketDisconnect:
        await end_session(session.id, summary="WebSocket disconnected")
