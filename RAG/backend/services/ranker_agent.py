"""
RAG System — Ranker Agent (FAZA 4.8)
Background agent that monitors retrieval quality metrics via judge scores.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

# Threshold below which a score is considered low quality
_LOW_QUALITY_THRESHOLD = 0.5
# Drop percentage that triggers degradation alert
_DEGRADATION_THRESHOLD_PCT = 10.0


class RankerAgent:
    """Background agent that monitors retrieval quality metrics."""

    async def get_quality_summary(self, db: AsyncSession, hours: int = 24) -> dict:
        """Get average judge scores for the last N hours.

        Returns aggregated stats plus a trend indicator comparing last half
        of the window against the first half.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)

        # Query assistant messages with judge scores in the time window
        result = await db.execute(
            select(
                func.count(ChatMessage.id),
                func.avg(ChatMessage.groundedness_score),
                func.avg(ChatMessage.completeness_score),
                func.avg(ChatMessage.relevance_score),
            ).where(
                and_(
                    ChatMessage.role == "assistant",
                    ChatMessage.created_at >= since,
                    ChatMessage.groundedness_score.isnot(None),
                )
            )
        )
        row = result.one()
        total = row[0] or 0
        avg_ground = round(float(row[1]), 4) if row[1] is not None else None
        avg_complete = round(float(row[2]), 4) if row[2] is not None else None
        avg_relev = round(float(row[3]), 4) if row[3] is not None else None

        # Count low-quality queries (any score below threshold)
        lq_result = await db.execute(
            select(func.count(ChatMessage.id)).where(
                and_(
                    ChatMessage.role == "assistant",
                    ChatMessage.created_at >= since,
                    ChatMessage.groundedness_score.isnot(None),
                    (
                        (ChatMessage.groundedness_score < _LOW_QUALITY_THRESHOLD)
                        | (ChatMessage.completeness_score < _LOW_QUALITY_THRESHOLD)
                        | (ChatMessage.relevance_score < _LOW_QUALITY_THRESHOLD)
                    ),
                )
            )
        )
        low_quality_count = lq_result.scalar_one() or 0

        # Trend: compare last half vs first half of the window
        trend = await self._compute_trend(db, hours)

        return {
            "period_hours": hours,
            "total_queries": total,
            "avg_groundedness": avg_ground,
            "avg_completeness": avg_complete,
            "avg_relevance": avg_relev,
            "low_quality_count": low_quality_count,
            "trend": trend,
        }

    async def _compute_trend(self, db: AsyncSession, hours: int) -> str:
        """Compare last (hours/2) vs previous (hours/2) average scores."""
        now = datetime.now(timezone.utc)
        half = hours / 2
        midpoint = now - timedelta(hours=half)
        start = now - timedelta(hours=hours)

        async def _avg_score(since: datetime, until: datetime) -> float | None:
            r = await db.execute(
                select(
                    func.avg(ChatMessage.groundedness_score),
                    func.avg(ChatMessage.completeness_score),
                    func.avg(ChatMessage.relevance_score),
                ).where(
                    and_(
                        ChatMessage.role == "assistant",
                        ChatMessage.created_at >= since,
                        ChatMessage.created_at < until,
                        ChatMessage.groundedness_score.isnot(None),
                    )
                )
            )
            row = r.one()
            vals = [v for v in (row[0], row[1], row[2]) if v is not None]
            if not vals:
                return None
            return sum(float(v) for v in vals) / len(vals)

        recent_avg = await _avg_score(midpoint, now)
        previous_avg = await _avg_score(start, midpoint)

        if recent_avg is None or previous_avg is None or previous_avg == 0:
            return "stable"

        change_pct = ((recent_avg - previous_avg) / previous_avg) * 100

        if change_pct <= -5:
            return "degrading"
        elif change_pct >= 5:
            return "improving"
        return "stable"

    async def get_low_quality_queries(
        self,
        db: AsyncSession,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[dict]:
        """Return recent queries where any judge score fell below threshold.

        Looks up the user message that preceded each low-quality assistant message.
        """
        result = await db.execute(
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.role == "assistant",
                    ChatMessage.groundedness_score.isnot(None),
                    (
                        (ChatMessage.groundedness_score < threshold)
                        | (ChatMessage.completeness_score < threshold)
                        | (ChatMessage.relevance_score < threshold)
                    ),
                )
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        assistant_msgs = result.scalars().all()

        output = []
        for msg in assistant_msgs:
            # Find the preceding user message in the same chat session
            prev_result = await db.execute(
                select(ChatMessage)
                .where(
                    and_(
                        ChatMessage.chat_id == msg.chat_id,
                        ChatMessage.role == "user",
                        ChatMessage.id < msg.id,
                    )
                )
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
            prev_msg = prev_result.scalar_one_or_none()
            query_text = prev_msg.content if prev_msg else ""

            output.append(
                {
                    "chat_id": msg.chat_id,
                    "query": query_text,
                    "groundedness": msg.groundedness_score,
                    "completeness": msg.completeness_score,
                    "relevance": msg.relevance_score,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )

        return output

    async def check_degradation(self, db: AsyncSession) -> dict | None:
        """Compare recent quality (last 6h) vs baseline (previous 24h).

        Returns None if not enough data, or a degradation report dict.
        """
        now = datetime.now(timezone.utc)
        recent_since = now - timedelta(hours=6)
        baseline_since = now - timedelta(hours=30)  # 24h before the 6h window

        async def _metric_avgs(since: datetime, until: datetime) -> dict[str, float | None]:
            r = await db.execute(
                select(
                    func.count(ChatMessage.id),
                    func.avg(ChatMessage.groundedness_score),
                    func.avg(ChatMessage.completeness_score),
                    func.avg(ChatMessage.relevance_score),
                ).where(
                    and_(
                        ChatMessage.role == "assistant",
                        ChatMessage.created_at >= since,
                        ChatMessage.created_at < until,
                        ChatMessage.groundedness_score.isnot(None),
                    )
                )
            )
            row = r.one()
            return {
                "count": row[0] or 0,
                "groundedness": float(row[1]) if row[1] is not None else None,
                "completeness": float(row[2]) if row[2] is not None else None,
                "relevance": float(row[3]) if row[3] is not None else None,
            }

        recent = await _metric_avgs(recent_since, now)
        baseline = await _metric_avgs(baseline_since, recent_since)

        # Need at least 3 data points in each window
        if recent["count"] < 3 or baseline["count"] < 3:
            return None

        metrics = ["groundedness", "completeness", "relevance"]
        worst_metric = None
        worst_drop = 0.0

        for metric in metrics:
            r_val = recent.get(metric)
            b_val = baseline.get(metric)
            if r_val is None or b_val is None or b_val == 0:
                continue
            drop_pct = ((b_val - r_val) / b_val) * 100
            if drop_pct > worst_drop:
                worst_drop = drop_pct
                worst_metric = metric
                worst_recent = r_val
                worst_baseline = b_val

        if worst_metric is None:
            return None

        degraded = worst_drop >= _DEGRADATION_THRESHOLD_PCT

        return {
            "degraded": degraded,
            "metric": worst_metric,
            "recent_avg": round(worst_recent, 4),
            "baseline_avg": round(worst_baseline, 4),
            "drop_percent": round(worst_drop, 2),
        }
