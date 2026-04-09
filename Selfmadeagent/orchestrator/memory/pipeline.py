"""3-tier memory retrieval pipeline with weighted RRF reranking."""

from __future__ import annotations

import logging
from typing import Optional

from agent.context_manager import count_tokens
from memory.working import WorkingMemory
from memory.episodic import EpisodicMemory
from memory.reranker import rerank_rrf

logger = logging.getLogger(__name__)


class MemoryPipeline:
    def __init__(
        self,
        working: Optional[WorkingMemory] = None,
        episodic: Optional[EpisodicMemory] = None,
    ):
        self.working = working
        self.episodic = episodic

    async def retrieve(
        self, query: str, session_id: str, budget_tokens: int = 2000
    ) -> str:
        """Run full 3-tier retrieval. Returns formatted context string."""
        parts = []

        # Tier 1: Working memory (instant, no DB)
        if self.working:
            working_ctx = self.working.get_relevant(query)
            if working_ctx:
                parts.append(f"### Working Memory\n{working_ctx}")

        # Tier 2: Episodic (patterns + episodes)
        if self.episodic:
            patterns = await self.episodic.search_patterns(query, top_k=3)
            if patterns:
                pattern_text = "\n".join(
                    f"- Pattern: {p['pattern']} → Solution: {p['solution']} (confidence: {p['confidence']:.1f}, verified: {p.get('verified', False)})"
                    for p in patterns
                )
                parts.append(f"### Learned Patterns\n{pattern_text}")

            episodes = await self.episodic.search_episodes(query, top_k=3)
            if episodes:
                ep_text = "\n".join(
                    f"- [{e['event_type']}] {e['content'][:150]}"
                    for e in episodes
                )
                parts.append(f"### Past Experience\n{ep_text}")

        # Combine and fit to token budget
        full_text = "\n\n".join(parts)
        tokens = count_tokens(full_text)
        if tokens > budget_tokens:
            # Truncate from the end
            while count_tokens(full_text) > budget_tokens and parts:
                parts.pop()
                full_text = "\n\n".join(parts)

        return full_text
