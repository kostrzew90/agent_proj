"""
RAG System — LLM-based reranker.
Scores retrieved chunks on relevance + specificity + coverage, applies hybrid
RRF merge and diversity cap, returns top-K.
Single LLM call for all chunks — fast enough for interactive use.
"""

import logging
import re
import time

from pydantic import BaseModel, Field

from config import settings
from core.llm import AsyncLLMClient
from core.retriever import RetrievalResult

logger = logging.getLogger("rag.core.llm_reranker")

_SYSTEM_PROMPT = """\
You are a document relevance scorer for a RAG system.
Given a user query and numbered document chunks, score each chunk on:
- relevance (0-5): how directly does this chunk answer the query?
  5 = directly answers, 3 = somewhat related, 0 = unrelated
- specificity (0-5): does this chunk contain concrete facts, numbers, or precise details?
  5 = very specific, 3 = mixed, 0 = vague generalities
- coverage (0-5): does this chunk contain actionable info that helps answer the query?
  5 = directly usable, 3 = partially useful, 0 = just background/definitions

Do NOT prioritize:
- generic introductions or definitions without context
- legal disclaimers, copyright notices, or boilerplate
- navigation/menu text or metadata
- repeated content from earlier in the document
- chunks that only mention the topic without providing answers

Respond with ONLY a JSON object, no explanation, no markdown:
{"scores": [{"id": <chunk_number>, "relevance": <0-5>, "specificity": <0-5>, "coverage": <0-5>}, ...]}"""


# ---------------------------------------------------------------------------
# Pydantic models for LLM output validation
# ---------------------------------------------------------------------------

class ChunkScore(BaseModel):
    id: int
    relevance: int = Field(ge=0, le=5)
    specificity: int = Field(ge=0, le=5)
    coverage: int = Field(ge=0, le=5)

    @property
    def total(self) -> float:
        return 0.5 * self.relevance + 0.2 * self.specificity + 0.3 * self.coverage


class RerankerScores(BaseModel):
    scores: list[ChunkScore]


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _parse_scores(text: str) -> list[ChunkScore]:
    """Extract, validate, and sort ChunkScore list from LLM output (desc total)."""
    # Strip <think>...</think> blocks (qwen3 chain-of-thought)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    parsed: RerankerScores | None = None

    # Attempt 1: direct JSON parse via pydantic
    try:
        parsed = RerankerScores.model_validate_json(text)
    except Exception:
        pass

    # Attempt 2: regex extract inner JSON object, then pydantic
    if parsed is None:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = RerankerScores.model_validate_json(match.group())
            except Exception:
                pass

    if parsed is None:
        return []

    return sorted(parsed.scores, key=lambda s: s.total, reverse=True)


def _hybrid_merge(
    scores: list[ChunkScore],
    results: list[RetrievalResult],
    llm_weight: float = 0.7,
) -> list[tuple[RetrievalResult, float]]:
    """
    Combine LLM scores (normalized to [0,1]) with RRF scores (normalized to [0,1]).
    Returns list of (result, final_score) sorted descending by final_score.
    """
    rrf_weight = 1.0 - llm_weight

    # Normalize RRF scores
    max_rrf = max((r.score for r in results), default=1.0) or 1.0
    rrf_norm = {r.chunk_id: r.score / max_rrf for r in results}

    # Map 1-based LLM ids → result by position
    index_map = {i + 1: r for i, r in enumerate(results)}
    llm_norm: dict[int, float] = {}
    for s in scores:
        r = index_map.get(s.id)
        if r is not None:
            llm_norm[r.chunk_id] = s.total / 5.0

    merged: list[tuple[RetrievalResult, float]] = []
    for r in results:
        llm_s = llm_norm.get(r.chunk_id, 0.0)
        rrf_s = rrf_norm.get(r.chunk_id, 0.0)
        final = llm_weight * llm_s + rrf_weight * rrf_s
        merged.append((r, final))

    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


def _apply_diversity(
    merged: list[tuple[RetrievalResult, float]],
    top_k: int,
    max_per_section: int = 2,
) -> list[RetrievalResult]:
    """
    Apply diversity cap: at most max_per_section chunks from the same
    (document_id, section_title) pair. Returns up to top_k results.
    """
    section_counts: dict[tuple, int] = {}
    out: list[RetrievalResult] = []
    for r, _ in merged:
        key = (r.document_id, r.section_title or "_no_section")
        if section_counts.get(key, 0) >= max_per_section:
            continue
        section_counts[key] = section_counts.get(key, 0) + 1
        out.append(r)
        if len(out) >= top_k:
            break
    return out


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LLMReranker:
    """
    Reranks RRF retrieval results using a fast LLM judge.
    Pipeline: LLM scoring → hybrid merge (LLM + RRF) → diversity cap → top-K.
    Uses the same model as ResponseJudge (qwen3:1.7b or Gemini Flash).
    """

    def __init__(self):
        if settings.ai.openrouter_api_key:
            from core.openrouter import OpenRouterClient
            self._client = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_judge_model,
            )
        else:
            self._client = AsyncLLMClient(
                base_url=settings.ai.ollama_url,
                model=settings.ai.judge_model,
            )

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """
        Score and sort results via LLM + hybrid RRF merge + diversity cap.
        Falls back to original RRF order on any error.
        """
        t0 = time.monotonic()
        effective_top_k = top_k if top_k is not None else settings.retrieval.reranker_top_k
        llm_weight: float = getattr(settings.retrieval, "reranker_llm_weight", 0.7)
        max_per_section: int = getattr(settings.retrieval, "reranker_max_per_section", 2)
        content_truncate: int = getattr(settings.retrieval, "reranker_content_truncate", 600)
        fallback_used = False

        if not results:
            return []

        if not settings.retrieval.reranker_enabled:
            return results[:effective_top_k]

        chunks_text = "\n\n".join(
            f"[{i + 1}] {r.content[:content_truncate]}" for i, r in enumerate(results)
        )
        prompt = f"Query: {query}\n\nChunks:\n{chunks_text}"

        try:
            result = await self._client.generate(
                prompt=prompt,
                system=_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=512,
            )
            ranked_scores = _parse_scores(result.text)
        except Exception as exc:
            logger.warning("LLM reranker failed (%s) — using RRF order", exc)
            fallback_used = True
            ranked_scores = []

        if not ranked_scores:
            if not fallback_used:
                logger.warning("LLM reranker returned no valid scores — using RRF order")
                fallback_used = True
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "rerank query=%r n_in=%d n_out=%d latency_ms=%.0f fallback=%s",
                query[:60], len(results), effective_top_k, elapsed_ms, fallback_used,
            )
            return results[:effective_top_k]

        # Hybrid merge: 0.7 * LLM_normalized + 0.3 * RRF_normalized
        merged = _hybrid_merge(ranked_scores, results, llm_weight=llm_weight)

        # Diversity cap: max max_per_section chunks per (document_id, section_title)
        reranked = _apply_diversity(merged, top_k=effective_top_k, max_per_section=max_per_section)

        # Fill remaining slots from original order if diversity filtered too many
        if len(reranked) < effective_top_k:
            seen_ids = {r.chunk_id for r in reranked}
            for r in results:
                if r.chunk_id not in seen_ids:
                    reranked.append(r)
                    seen_ids.add(r.chunk_id)
                if len(reranked) >= effective_top_k:
                    break

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "rerank query=%r n_in=%d n_out=%d latency_ms=%.0f fallback=%s",
            query[:60], len(results), len(reranked), elapsed_ms, fallback_used,
        )
        return reranked

    async def close(self):
        await self._client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
