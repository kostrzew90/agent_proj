"""
memory.py — Hermes 3-layer memory (Session + Persistent).

Session (episodic):  "co się stało?" — auto-saved per interaction
Persistent (semantic): "kim jesteś?" — user-saved facts with embeddings
Procedural (skills): markdown files in /skills/ — handled separately

Storage: Postgres + pgvector (hermes_session_memory, hermes_persistent_memory)
in the same `rag` database on :5434.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx
import psycopg2
import psycopg2.extras

_DSN: str = os.environ.get(
    "HERMES_RECALL_DSN",
    "postgresql://rag:ragpass@host.docker.internal:5434/rag",
)
_OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
_EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")

_conn: Optional[Any] = None


def _get_conn():
    """Lazy singleton Postgres connection."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_DSN)
        _conn.autocommit = True
    return _conn


def _embed(text: str) -> list[float] | None:
    """Get embedding vector from Ollama. Returns None on error."""
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_OLLAMA_URL}/api/embeddings",
                json={"model": _EMBEDDING_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as exc:
        print(f"[memory] embedding error: {exc}", flush=True)
        return None


# ── Session memory (episodic) ───────────────────────────────────

def save_session(user_message: str, reply: str, skill_name: str = "", latency_ms: int = 0) -> int:
    """Save an interaction to session memory. Returns row id."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO hermes_session_memory "
            "(user_message, reply, skill_name, latency_ms) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user_message, reply, skill_name, latency_ms),
        )
        return cur.fetchone()[0]


def search_sessions(query: str, limit: int = 5) -> list[dict]:
    """Full-text search across session memory (tsvector + tsquery)."""
    conn = _get_conn()
    # Convert user query to tsquery: split words, join with &
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return []
    tsq = " & ".join(words)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, ts, user_message, reply, skill_name, latency_ms, "
            "ts_rank(tsv, to_tsquery('simple', %s)) AS rank "
            "FROM hermes_session_memory "
            "WHERE tsv @@ to_tsquery('simple', %s) "
            "ORDER BY rank DESC, ts DESC "
            "LIMIT %s",
            (tsq, tsq, limit),
        )
        rows = cur.fetchall()
    return [
        {"id": r["id"], "ts": str(r["ts"]), "user_message": r["user_message"],
         "reply": r["reply"], "skill_name": r["skill_name"],
         "latency_ms": r["latency_ms"]}
        for r in rows
    ]


def recent_sessions(limit: int = 10) -> list[dict]:
    """Return N most recent interactions."""
    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, ts, user_message, reply, skill_name, latency_ms "
            "FROM hermes_session_memory ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {"id": r["id"], "ts": str(r["ts"]), "user_message": r["user_message"],
         "reply": r["reply"], "skill_name": r["skill_name"],
         "latency_ms": r["latency_ms"]}
        for r in rows
    ]


def session_count() -> int:
    """Total number of stored interactions."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hermes_session_memory")
        return cur.fetchone()[0]


# ── Persistent memory (semantic) ────────────────────────────────

def remember(fact: str, category: str = "general") -> int:
    """Save a persistent fact with embedding. Returns row id."""
    conn = _get_conn()
    emb = _embed(fact)
    with conn.cursor() as cur:
        if emb:
            cur.execute(
                "INSERT INTO hermes_persistent_memory (fact, category, embedding) "
                "VALUES (%s, %s, %s) RETURNING id",
                (fact, category, str(emb)),
            )
        else:
            cur.execute(
                "INSERT INTO hermes_persistent_memory (fact, category) "
                "VALUES (%s, %s) RETURNING id",
                (fact, category),
            )
        return cur.fetchone()[0]


def forget(query: str) -> int:
    """Delete persistent facts matching FTS query. Returns count deleted."""
    conn = _get_conn()
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return 0
    tsq = " & ".join(words)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM hermes_persistent_memory "
            "WHERE tsv @@ to_tsquery('simple', %s)",
            (tsq,),
        )
        return cur.rowcount


def get_all_persistent(limit: int = 50) -> list[dict]:
    """Return all persistent facts, newest first."""
    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, ts, fact, category "
            "FROM hermes_persistent_memory ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {"id": r["id"], "ts": str(r["ts"]), "fact": r["fact"], "category": r["category"]}
        for r in rows
    ]


def search_persistent(query: str, limit: int = 5) -> list[dict]:
    """
    Semantic search on persistent memory.
    Uses embedding cosine similarity if available, falls back to FTS.
    """
    conn = _get_conn()
    emb = _embed(query)

    if emb:
        # Semantic search via pgvector
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, ts, fact, category, "
                "1 - (embedding <=> %s::vector) AS score "
                "FROM hermes_persistent_memory "
                "WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (str(emb), str(emb), limit),
            )
            rows = cur.fetchall()
        if rows:
            return [
                {"id": r["id"], "ts": str(r["ts"]), "fact": r["fact"],
                 "category": r["category"], "score": round(float(r["score"]), 3)}
                for r in rows
            ]

    # FTS fallback
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return get_all_persistent(limit=limit)
    tsq = " | ".join(words)  # OR for broader matching
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, ts, fact, category, "
            "ts_rank(tsv, to_tsquery('simple', %s)) AS score "
            "FROM hermes_persistent_memory "
            "WHERE tsv @@ to_tsquery('simple', %s) "
            "ORDER BY score DESC LIMIT %s",
            (tsq, tsq, limit),
        )
        rows = cur.fetchall()
    return [
        {"id": r["id"], "ts": str(r["ts"]), "fact": r["fact"],
         "category": r["category"], "score": round(float(r["score"]), 3)}
        for r in rows
    ]


def persistent_count() -> int:
    """Total number of stored persistent facts."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hermes_persistent_memory")
        return cur.fetchone()[0]


# ── Context builder (for skill calls) ──────────────────────────

def build_context(query: str = "", max_persistent: int = 10, max_recent: int = 3) -> str:
    """
    Build a context string from memory for injection into skill prompts.
    Uses semantic search for persistent facts if query given.
    """
    parts: list[str] = []

    # Persistent facts (semantic if query, all otherwise)
    if query:
        facts = search_persistent(query, limit=max_persistent)
    else:
        facts = get_all_persistent(limit=max_persistent)

    if facts:
        parts.append("Fakty o użytkowniku:")
        for f in facts:
            score = f.get("score", "")
            score_str = f" [{score}]" if score else ""
            parts.append(f"  - {f['fact']}{score_str}")

    # Recent sessions
    if query:
        sessions = search_sessions(query, limit=max_recent)
    else:
        sessions = recent_sessions(limit=max_recent)

    if sessions:
        parts.append("")
        parts.append("Ostatnie interakcje:")
        for s in sessions:
            msg_preview = s["user_message"][:80]
            reply_preview = s["reply"][:80]
            parts.append(f"  - [{s['ts'][:10]}] Q: {msg_preview}... → A: {reply_preview}...")

    return "\n".join(parts) if parts else ""
