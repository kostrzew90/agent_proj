"""
RAG System — Profile Service (FAZA 4.7)
Tracks user interests and preferred language from chat interactions.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import UserProfile

# Common Polish stop words to ignore when extracting topics
_PL_STOP = {
    "i", "w", "z", "na", "do", "to", "się", "że", "a", "nie", "jak",
    "co", "czy", "po", "ale", "o", "je", "mi", "go", "jej", "jego",
    "są", "jest", "być", "by", "tak", "ten", "ta", "te", "tego", "tej",
}

# Common English stop words to ignore
_EN_STOP = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "this",
    "that", "these", "those", "it", "its", "about", "what", "how",
    "when", "where", "who", "which", "i", "you", "we", "they", "he",
    "she", "me", "him", "her", "us", "them", "my", "your", "our",
}

_STOP_WORDS = _PL_STOP | _EN_STOP

# Polish character set for language detection
_PL_CHARS = set("ąęóśźżćńł")
_PL_COMMON_WORDS = {"jest", "nie", "jak", "czy", "się", "tego", "dla", "przy"}

_MAX_TOPICS = 50


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text using simple heuristics."""
    # Lowercase and split on non-alphanumeric (keep letters and digits)
    words = re.findall(r"[a-zA-ZąęóśźżćńłĄĘÓŚŹŻĆŃŁ]{3,}", text.lower())
    keywords = [w for w in words if w not in _STOP_WORDS]
    return keywords


class ProfileService:
    """Tracks user interests and preferred language from chat interactions."""

    async def get_or_create_profile(self, db: AsyncSession, user_id: int) -> UserProfile:
        """Get existing profile or create a new one."""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                frequent_topics={},
                preferred_language="auto",
                settings={},
            )
            db.add(profile)
            await db.flush()

        return profile

    async def update_topics(
        self,
        db: AsyncSession,
        user_id: int,
        query: str,
        chunks: list[str],
    ) -> None:
        """Extract topics from query+retrieved chunks and update frequent_topics JSONB.

        frequent_topics format: {"topic_name": count, ...}
        Uses simple keyword extraction (no LLM). Keeps top 50 topics max.
        """
        profile = await self.get_or_create_profile(db, user_id)

        # Extract keywords from query and the first 3 chunks (avoid noise from long context)
        combined_text = query + " " + " ".join(chunks[:3])
        keywords = _extract_keywords(combined_text)

        if not keywords:
            return

        topics: dict = dict(profile.frequent_topics or {})
        for kw in keywords:
            topics[kw] = topics.get(kw, 0) + 1

        # Keep top 50 by count
        if len(topics) > _MAX_TOPICS:
            topics = dict(
                sorted(topics.items(), key=lambda x: x[1], reverse=True)[:_MAX_TOPICS]
            )

        profile.frequent_topics = topics
        profile.updated_at = datetime.now(timezone.utc)
        await db.commit()

    async def detect_language(
        self, db: AsyncSession, user_id: int, query: str
    ) -> str:
        """Detect query language and update preferred_language if a pattern emerges.

        Heuristic:
        - Polish chars (ąęóśźżćńł) or common PL words → 'pl'
        - Otherwise → 'en'
        - Update profile.preferred_language after 3+ consistent queries.
        """
        # Detect language of this query
        query_lower = query.lower()
        has_pl_chars = any(c in _PL_CHARS for c in query_lower)
        has_pl_words = any(w in query_lower.split() for w in _PL_COMMON_WORDS)
        detected = "pl" if (has_pl_chars or has_pl_words) else "en"

        profile = await self.get_or_create_profile(db, user_id)
        settings_data: dict = dict(profile.settings or {})

        # Track recent language detections (rolling window of last 5)
        lang_history: list = settings_data.get("lang_history", [])
        lang_history.append(detected)
        lang_history = lang_history[-5:]  # keep last 5
        settings_data["lang_history"] = lang_history

        # Update preferred_language if 3+ consecutive consistent detections
        if len(lang_history) >= 3 and len(set(lang_history[-3:])) == 1:
            consistent_lang = lang_history[-1]
            if profile.preferred_language != consistent_lang:
                profile.preferred_language = consistent_lang

        profile.settings = settings_data
        profile.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return detected

    async def get_user_topics(self, db: AsyncSession, user_id: int) -> dict:
        """Return frequent_topics sorted by count descending."""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None or not profile.frequent_topics:
            return {}

        return dict(
            sorted(profile.frequent_topics.items(), key=lambda x: x[1], reverse=True)
        )
