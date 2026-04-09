"""Reflection engine — Karpathy-style session-end learning."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from agent.providers import call_llm, get_provider_chain

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    summary: str
    reflection: str
    patterns: list[dict] = field(default_factory=list)
    repeated_mistakes: list[dict] = field(default_factory=list)


class ReflectionEngine:
    def __init__(self, episodic, llm_provider_chain=None):
        self.episodic = episodic
        self.provider_chain = llm_provider_chain or get_provider_chain()

    async def _ask_llm(self, prompt: str, system: str) -> str:
        """Helper to call LLM for reflection tasks."""
        response = await call_llm(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            provider_chain=self.provider_chain,
        )
        return response.choices[0].message.content or ""

    async def reflect_on_session(self, session_id: str) -> ReflectionResult:
        """Run full reflection pipeline at session end."""
        episodes = await self.episodic.get_session_episodes(session_id)
        if not episodes:
            return ReflectionResult(summary="Empty session", reflection="Nothing to reflect on")

        episodes_text = "\n".join(
            f"[{e['event_type']}] {e['content'][:200]} → {e.get('outcome', '?')}"
            for e in episodes
        )

        # 1. Summary
        summary = await self._ask_llm(
            prompt=f"Session events:\n{episodes_text}",
            system="Generate a 3-5 sentence summary of what was done and the outcome. Be factual.",
        )

        # 2. Reflection
        reflection = await self._ask_llm(
            prompt=f"Session summary: {summary}\n\nWhat could have been done better?",
            system="Identify 1-3 concrete, specific improvements. No generic advice.",
        )

        # 3. Compare with past sessions
        repeated = []
        similar_sessions = await self.episodic.search_episodes(summary, top_k=3)
        if similar_sessions:
            past_ctx = "\n".join(f"- {s['content'][:150]}" for s in similar_sessions)
            try:
                repeated_raw = await self._ask_llm(
                    prompt=f"Current: {summary}\n\nPast:\n{past_ctx}\n\nAny repeated mistakes?",
                    system='Return JSON: {"repeated": [{"mistake": "...", "frequency": 1}]}. If none, return {"repeated": []}.',
                )
                repeated = json.loads(repeated_raw).get("repeated", [])
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse repeated mistakes: {e}")

        # 4. Extract patterns
        patterns = []
        try:
            patterns_raw = await self._ask_llm(
                prompt=f"Summary: {summary}\nReflection: {reflection}\n\nExtract problem→solution pairs.",
                system='Return JSON array: [{"pattern": "...", "solution": "...", "confidence": 0.0-1.0}]. Max 5 patterns.',
            )
            # Handle markdown code blocks
            text = patterns_raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            patterns = json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse patterns: {e}")

        # 5. Deduplicate and store
        for p in patterns:
            if not isinstance(p, dict) or "pattern" not in p:
                continue
            confidence = float(p.get("confidence", 0.5))

            existing = await self.episodic.find_similar_pattern(p["pattern"], threshold=0.85)
            if existing:
                new_conf = min(1.0, existing["confidence"] + 0.1)
                await self.episodic.update_pattern(existing["id"], confidence=new_conf)
            else:
                store, review = self.episodic.should_store_with_review(confidence)
                if store:
                    await self.episodic.store_pattern(
                        pattern=p["pattern"],
                        solution=p.get("solution", ""),
                        confidence=confidence,
                        needs_review=review,
                        source="reflection",
                        source_session=session_id,
                    )

        # 6. Store summary
        await self.episodic.store_summary(session_id, summary, reflection)

        return ReflectionResult(
            summary=summary,
            reflection=reflection,
            patterns=patterns,
            repeated_mistakes=repeated,
        )
