"""Tier 2: Episodic memory — sessions, episodes, learned patterns."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

SOURCE_WEIGHTS = {
    "user-correction": 1.2,
    "reflection": 1.0,
    "pattern-extraction": 0.9,
    "auto-bootstrap": 0.8,
}


def compute_weight(
    confidence: float,
    verified: bool = False,
    times_applied: int = 0,
    times_failed: int = 0,
    source: str = "reflection",
    days_old: int = 0,
) -> float:
    """Compute weighted score for retrieval ranking."""
    w = confidence

    # Recency: decay over 30 days, floor 0.7
    w *= max(0.7, 1.0 - 0.3 * (days_old / 30))

    # Verification bonus
    if verified:
        w *= 1.3

    # Success rate
    total = times_applied + times_failed
    if total > 0:
        rate = times_applied / total
        w *= 0.5 + 0.7 * rate  # range: 0.5 (all fail) to 1.2 (all success)

    # Source quality
    w *= SOURCE_WEIGHTS.get(source, 1.0)

    return w


class EpisodicMemory:
    """Manage episodic memory: session summaries, episodes, learned patterns."""

    def __init__(self, pool: Optional[asyncpg.Pool], embedder=None):
        self.pool = pool
        self.embedder = embedder

    @staticmethod
    def should_store(confidence: float) -> bool:
        return confidence >= 0.5

    @staticmethod
    def should_store_with_review(confidence: float) -> tuple[bool, bool]:
        """Returns (should_store, needs_review)."""
        if confidence < 0.5:
            return False, False
        return True, confidence < 0.7

    async def store_pattern(
        self,
        pattern: str,
        solution: str,
        confidence: float,
        needs_review: bool = False,
        source: str = "reflection",
        source_session: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[int]:
        """Store a learned pattern with embedding."""
        if not self.should_store(confidence):
            return None

        embedding = None
        if self.embedder:
            embedding = await self.embedder.embed_one(f"{pattern} {solution}")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO learned_patterns
                   (pattern, solution, confidence, needs_review, source, source_session, tags, embedding)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   RETURNING id""",
                pattern, solution, confidence, needs_review, source,
                uuid.UUID(source_session) if source_session else None,
                tags or [], embedding,
            )
            return row["id"]

    async def search_patterns(self, query: str, top_k: int = 5) -> list[dict]:
        """Search learned patterns by embedding similarity."""
        if not self.embedder:
            return []

        embedding = await self.embedder.embed_one(query)
        if not embedding:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, pattern, solution, confidence, times_applied, times_failed,
                          source, verified, verified_by, needs_review,
                          EXTRACT(EPOCH FROM (NOW() - COALESCE(last_applied, NOW()))) / 86400 as days_old,
                          1 - (embedding <=> $1::vector) as similarity
                   FROM learned_patterns
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                str(embedding), top_k,
            )

        results = []
        for r in rows:
            d = dict(r)
            d["weighted_score"] = compute_weight(
                confidence=d["confidence"],
                verified=d.get("verified", False),
                times_applied=d.get("times_applied", 0),
                times_failed=d.get("times_failed", 0),
                source=d.get("source", "reflection"),
                days_old=int(d.get("days_old", 0)),
            )
            results.append(d)

        return sorted(results, key=lambda x: x["weighted_score"], reverse=True)

    async def find_similar_pattern(self, pattern_text: str, threshold: float = 0.85) -> Optional[dict]:
        """Find existing pattern similar to given text (for dedup)."""
        if not self.embedder:
            return None

        embedding = await self.embedder.embed_one(pattern_text)
        if not embedding:
            return None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, pattern, solution, confidence, times_applied
                   FROM learned_patterns
                   WHERE embedding IS NOT NULL
                     AND 1 - (embedding <=> $1::vector) > $2
                   ORDER BY embedding <=> $1::vector
                   LIMIT 1""",
                str(embedding), threshold,
            )

        return dict(row) if row else None

    async def update_pattern(self, pattern_id: int, confidence: Optional[float] = None):
        """Update pattern confidence."""
        if confidence is not None:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE learned_patterns SET confidence = $2 WHERE id = $1",
                    pattern_id, confidence,
                )

    async def increment_applied(self, pattern_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE learned_patterns SET times_applied = times_applied + 1, last_applied = NOW() WHERE id = $1",
                pattern_id,
            )

    async def increment_failed(self, pattern_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE learned_patterns SET times_failed = times_failed + 1 WHERE id = $1",
                pattern_id,
            )

    async def verify_pattern(self, pattern_id: int, verified_by: str = "multi-use"):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE learned_patterns SET verified = TRUE, verified_by = $2, verified_at = NOW() WHERE id = $1",
                pattern_id, verified_by,
            )

    async def store_summary(self, session_id: str, summary: str, reflection: str):
        """Store session summary and reflection as episodes."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE agent_sessions SET summary = $2 WHERE id = $1",
                uuid.UUID(session_id), summary,
            )
            await conn.execute(
                "INSERT INTO episodes (session_id, event_type, content, outcome) VALUES ($1, 'reflection', $2, 'completed')",
                uuid.UUID(session_id), reflection,
            )

    async def search_episodes(self, query: str, top_k: int = 5) -> list[dict]:
        """Search episodes by embedding similarity."""
        if not self.embedder:
            return []

        embedding = await self.embedder.embed_one(query)
        if not embedding:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, event_type, content, outcome, ts,
                          1 - (embedding <=> $1::vector) as similarity
                   FROM episodes
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                str(embedding), top_k,
            )

        return [dict(r) for r in rows]

    async def get_session_episodes(self, session_id: str) -> list[dict]:
        """Get all episodes for a session."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, event_type, content, outcome, ts FROM episodes WHERE session_id = $1 ORDER BY ts",
                uuid.UUID(session_id),
            )
        return [dict(r) for r in rows]
