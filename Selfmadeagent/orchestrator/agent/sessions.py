import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
import asyncpg
from langfuse.decorators import observe

DB_URL = os.getenv("AGENT_DB_URL", "postgresql://agent:agentpass@agent-db:5432/agent")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the DB connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
    return _pool


@dataclass
class Message:
    role: str  # "user", "assistant", "tool"
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


@dataclass
class Session:
    id: str
    goal: str | None = None
    status: str = "active"
    messages: list[Message] = field(default_factory=list)
    created_at: datetime | None = None


@observe(name="session_create")
async def create_session(goal: str | None = None, workspace_path: str | None = None) -> Session:
    """Create a new agent session in DB."""
    pool = await get_pool()
    session_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent_sessions (id, goal, workspace_path) VALUES ($1, $2, $3)",
            uuid.UUID(session_id), goal, workspace_path,
        )
    return Session(id=session_id, goal=goal, status="active")


@observe(name="session_get")
async def get_session(session_id: str) -> Session | None:
    """Retrieve a session from DB."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, goal, status, started_at FROM agent_sessions WHERE id = $1",
            uuid.UUID(session_id),
        )
    if not row:
        return None
    return Session(
        id=str(row["id"]),
        goal=row["goal"],
        status=row["status"],
        created_at=row["started_at"],
    )


@observe(name="session_list")
async def list_sessions(limit: int = 20) -> list[dict]:
    """List recent sessions."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, status, started_at FROM agent_sessions ORDER BY started_at DESC LIMIT $1",
            limit,
        )
    return [
        {"id": str(r["id"]), "goal": r["goal"], "status": r["status"], "started_at": str(r["started_at"])}
        for r in rows
    ]


@observe(name="session_end")
async def end_session(session_id: str, summary: str | None = None):
    """Mark a session as completed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent_sessions SET status = 'completed', ended_at = NOW(), summary = $2 WHERE id = $1",
            uuid.UUID(session_id), summary,
        )


async def add_episode(session_id: str, event_type: str, content: str, outcome: str | None = None):
    """Log an episode (event) to the session timeline."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO episodes (session_id, event_type, content, outcome) VALUES ($1, $2, $3, $4)",
            uuid.UUID(session_id), event_type, content, outcome,
        )
