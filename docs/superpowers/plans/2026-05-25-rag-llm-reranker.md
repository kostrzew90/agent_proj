# RAG LLM Reranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-based reranker between RRF retrieval and LLM generation that scores each chunk on relevance + specificity + coverage and returns the top-5 most useful chunks instead of the raw RRF top-10. LLM scores are combined with RRF scores in a hybrid merge (0.7 LLM + 0.3 RRF) and a diversity cap (max 2 chunks per section) is applied.

**Architecture:** New `LLMReranker` class in `core/llm_reranker.py` follows the same pattern as `ResponseJudge` — single async LLM call scoring all 10 chunks at once, returns sorted top-K. Pydantic models validate LLM output. Wired into `chat_service.py` after retrieval, before prompt building. Disabled by env var (`RETRIEVAL_RERANKER_ENABLED=false`) for A/B testing. Graceful fallback: if LLM fails, returns original RRF results.

**Tech Stack:** Python 3.11, `AsyncLLMClient` (Ollama qwen3:1.7b) or `OpenRouterClient` (Gemini Flash), pydantic + pydantic-settings, pytest + pytest-asyncio

---

## Files Created / Modified

| File | Action |
|------|--------|
| `RAG/backend/core/llm_reranker.py` | CREATE — `LLMReranker` class |
| `RAG/backend/tests/test_llm_reranker.py` | CREATE — unit tests |
| `RAG/backend/config.py` | MODIFY — expand `RetrievalSettings` with reranker knobs |
| `RAG/backend/services/chat_service.py` | MODIFY — instantiate reranker, call after retrieval, add trace span |

---

## Task 1: `llm_reranker.py` — core module

**Files:**
- Create: `RAG/backend/core/llm_reranker.py`
- Create: `RAG/backend/tests/__init__.py`
- Create: `RAG/backend/tests/test_llm_reranker.py`

### Step 1: Create test file

Create `RAG/backend/tests/__init__.py` (empty).

Create `RAG/backend/tests/test_llm_reranker.py`:

```python
"""Unit tests for LLMReranker."""
import pytest
from unittest.mock import AsyncMock, patch
from dataclasses import dataclass


# Stub RetrievalResult for tests (mirrors core/retriever.py)
@dataclass
class _FakeResult:
    chunk_id: int
    document_id: int
    content: str
    score: float
    page_number: int | None
    section_title: str | None
    document_name: str
    chunk_type: str
    semantic_score: float | None
    bm25_score: float | None


def _make_results(n: int, section_title: str | None = None):
    return [
        _FakeResult(
            chunk_id=i,
            document_id=1,
            content=f"chunk content {i}",
            score=1.0 / (i + 1),
            page_number=None,
            section_title=section_title,
            document_name="doc.pdf",
            chunk_type="text",
            semantic_score=None,
            bm25_score=None,
        )
        for i in range(n)
    ]


# 3-dim scoring: relevance, specificity, coverage
LLM_RESPONSE_OK = '''{
  "scores": [
    {"id": 1, "relevance": 5, "specificity": 4, "coverage": 5},
    {"id": 2, "relevance": 3, "specificity": 2, "coverage": 2},
    {"id": 3, "relevance": 4, "specificity": 5, "coverage": 3},
    {"id": 4, "relevance": 1, "specificity": 1, "coverage": 0},
    {"id": 5, "relevance": 2, "specificity": 3, "coverage": 1}
  ]
}'''


@pytest.mark.asyncio
async def test_rerank_sorts_by_score():
    """Chunks with higher LLM score come first after hybrid merge."""
    from core.llm_reranker import _parse_scores

    scores = _parse_scores(LLM_RESPONSE_OK)
    # id=1: 0.5*5 + 0.2*4 + 0.3*5 = 2.5 + 0.8 + 1.5 = 4.8 (highest)
    # id=3: 0.5*4 + 0.2*5 + 0.3*3 = 2.0 + 1.0 + 0.9 = 3.9
    # Expected order by total: id=1 (4.8) > id=3 (3.9) > ...
    assert scores[0].id == 1
    assert scores[1].id == 3


@pytest.mark.asyncio
async def test_rerank_returns_top_k():
    """Returns at most top_k results."""
    from core.llm_reranker import LLMReranker
    from core.llm import GenerationResult

    mock_result = GenerationResult(text=LLM_RESPONSE_OK, model="test")

    with patch("core.llm_reranker.settings") as mock_settings:
        mock_settings.ai.openrouter_api_key = ""
        mock_settings.ai.ollama_url = "http://localhost:11434"
        mock_settings.ai.judge_model = "qwen3:1.7b"
        mock_settings.retrieval.reranker_enabled = True
        mock_settings.retrieval.reranker_top_k = 3
        mock_settings.retrieval.reranker_llm_weight = 0.7
        mock_settings.retrieval.reranker_max_per_section = 2
        mock_settings.retrieval.reranker_content_truncate = 600

        reranker = LLMReranker()
        reranker._client = AsyncMock()
        reranker._client.generate = AsyncMock(return_value=mock_result)

        results = _make_results(5)
        reranked = await reranker.rerank("test query", results, top_k=3)

    assert len(reranked) == 3


@pytest.mark.asyncio
async def test_rerank_fallback_on_llm_error():
    """Returns original results sliced to top_k when LLM fails."""
    from core.llm_reranker import LLMReranker

    with patch("core.llm_reranker.settings") as mock_settings:
        mock_settings.ai.openrouter_api_key = ""
        mock_settings.ai.ollama_url = "http://localhost:11434"
        mock_settings.ai.judge_model = "qwen3:1.7b"
        mock_settings.retrieval.reranker_enabled = True
        mock_settings.retrieval.reranker_top_k = 5
        mock_settings.retrieval.reranker_llm_weight = 0.7
        mock_settings.retrieval.reranker_max_per_section = 2
        mock_settings.retrieval.reranker_content_truncate = 600

        reranker = LLMReranker()
        reranker._client = AsyncMock()
        reranker._client.generate = AsyncMock(side_effect=Exception("timeout"))

        results = _make_results(10)
        reranked = await reranker.rerank("test query", results, top_k=5)

    assert len(reranked) == 5
    # Fallback preserves original RRF order
    assert reranked[0].chunk_id == 0


@pytest.mark.asyncio
async def test_rerank_disabled_returns_top_k_unchanged():
    """When reranker_enabled=False, returns original results[:top_k]."""
    from core.llm_reranker import LLMReranker

    with patch("core.llm_reranker.settings") as mock_settings:
        mock_settings.ai.openrouter_api_key = ""
        mock_settings.ai.ollama_url = "http://localhost:11434"
        mock_settings.ai.judge_model = "qwen3:1.7b"
        mock_settings.retrieval.reranker_enabled = False
        mock_settings.retrieval.reranker_top_k = 5
        mock_settings.retrieval.reranker_llm_weight = 0.7
        mock_settings.retrieval.reranker_max_per_section = 2
        mock_settings.retrieval.reranker_content_truncate = 600

        reranker = LLMReranker()
        reranker._client = AsyncMock()

        results = _make_results(10)
        reranked = await reranker.rerank("test query", results, top_k=5)

    reranker._client.generate.assert_not_called()
    assert len(reranked) == 5
    assert reranked[0].chunk_id == 0


@pytest.mark.asyncio
async def test_rerank_empty_input():
    """Empty input returns empty list without LLM call."""
    from core.llm_reranker import LLMReranker

    with patch("core.llm_reranker.settings") as mock_settings:
        mock_settings.ai.openrouter_api_key = ""
        mock_settings.ai.ollama_url = "http://localhost:11434"
        mock_settings.ai.judge_model = "qwen3:1.7b"
        mock_settings.retrieval.reranker_enabled = True
        mock_settings.retrieval.reranker_content_truncate = 600

        reranker = LLMReranker()
        reranker._client = AsyncMock()

        reranked = await reranker.rerank("test query", [], top_k=5)

    assert reranked == []
    reranker._client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_hybrid_merge_combines_scores():
    """A chunk with low LLM score but high RRF score is not fully discarded."""
    from core.llm_reranker import _hybrid_merge, ChunkScore, RerankerScores

    # Two chunks: chunk 0 has RRF score 1.0, chunk 1 has RRF score 0.1
    results = _make_results(2)
    results[0].score = 0.1   # low RRF
    results[1].score = 1.0   # high RRF

    # LLM heavily favours chunk 0 (index 1 in 1-based prompt)
    scores = RerankerScores(scores=[
        ChunkScore(id=1, relevance=5, specificity=5, coverage=5),  # chunk 0
        ChunkScore(id=2, relevance=0, specificity=0, coverage=0),  # chunk 1
    ])

    merged = _hybrid_merge(scores.scores, results, llm_weight=0.7)
    # chunk 1 (high RRF) should get a meaningful final score > 0
    chunk1_score = next(score for r, score in merged if r.chunk_id == 1)
    assert chunk1_score > 0.0, "High-RRF chunk should not be fully discarded"


@pytest.mark.asyncio
async def test_diversity_caps_per_section():
    """10 chunks all from same section, top_k=5, max_per_section=2 → 2 chunks returned."""
    from core.llm_reranker import _apply_diversity

    results = _make_results(10, section_title="Introduction")
    # Build merged as (result, score) pairs — high scores descending
    merged = [(r, 1.0 - i * 0.05) for i, r in enumerate(results)]

    out = _apply_diversity(merged, top_k=5, max_per_section=2)
    assert len(out) == 2


@pytest.mark.asyncio
async def test_pydantic_validation_rejects_invalid_scores():
    """LLM returns relevance=99 — pydantic validation should catch it and fall back."""
    from core.llm_reranker import LLMReranker
    from core.llm import GenerationResult

    bad_response = '{"scores": [{"id": 1, "relevance": 99, "specificity": 3, "coverage": 2}]}'
    mock_result = GenerationResult(text=bad_response, model="test")

    with patch("core.llm_reranker.settings") as mock_settings:
        mock_settings.ai.openrouter_api_key = ""
        mock_settings.ai.ollama_url = "http://localhost:11434"
        mock_settings.ai.judge_model = "qwen3:1.7b"
        mock_settings.retrieval.reranker_enabled = True
        mock_settings.retrieval.reranker_top_k = 3
        mock_settings.retrieval.reranker_llm_weight = 0.7
        mock_settings.retrieval.reranker_max_per_section = 2
        mock_settings.retrieval.reranker_content_truncate = 600

        reranker = LLMReranker()
        reranker._client = AsyncMock()
        reranker._client.generate = AsyncMock(return_value=mock_result)

        results = _make_results(5)
        reranked = await reranker.rerank("test query", results, top_k=3)

    # Should fall back to RRF order (original first chunk preserved)
    assert len(reranked) == 3
    assert reranked[0].chunk_id == 0
```

- [ ] **Step 2: Run tests — verify they fail**

Run from inside the RAG backend container or with the right Python path:
```bash
cd RAG/backend
python -m pytest tests/test_llm_reranker.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'core.llm_reranker'`

- [ ] **Step 3: Create `RAG/backend/core/llm_reranker.py`**

```python
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd RAG/backend
python -m pytest tests/test_llm_reranker.py -v
```

Expected:
```
test_llm_reranker.py::test_rerank_sorts_by_score PASSED
test_llm_reranker.py::test_rerank_returns_top_k PASSED
test_llm_reranker.py::test_rerank_fallback_on_llm_error PASSED
test_llm_reranker.py::test_rerank_disabled_returns_top_k_unchanged PASSED
test_llm_reranker.py::test_rerank_empty_input PASSED
test_llm_reranker.py::test_hybrid_merge_combines_scores PASSED
test_llm_reranker.py::test_diversity_caps_per_section PASSED
test_llm_reranker.py::test_pydantic_validation_rejects_invalid_scores PASSED
8 passed
```

If tests fail with import errors, ensure pytest is run from `RAG/backend/` so that `core/` is on the path. Add `sys.path.insert(0, ".")` at the top of the test file if needed.

- [ ] **Step 5: Commit**

```bash
git add RAG/backend/core/llm_reranker.py RAG/backend/tests/__init__.py RAG/backend/tests/test_llm_reranker.py
git commit -m "feat(rag): add LLMReranker — 3-dim scoring, hybrid RRF merge, diversity cap"
```

---

## Task 2: Config + chat_service.py integration

**Files:**
- Modify: `RAG/backend/config.py`
- Modify: `RAG/backend/services/chat_service.py`

- [ ] **Step 1: Expand `RetrievalSettings` in `config.py`**

Find:
```python
class RetrievalSettings(BaseSettings):
    top_k: int = 10
    semantic_weight: float = 0.7
    bm25_weight: float = 0.3

    model_config = {"env_prefix": "RETRIEVAL_", "extra": "ignore"}
```

Replace with:
```python
class RetrievalSettings(BaseSettings):
    top_k: int = 10
    semantic_weight: float = 0.7
    bm25_weight: float = 0.3
    reranker_enabled: bool = True
    reranker_top_k: int = 5
    reranker_llm_weight: float = 0.7        # hybrid merge: 0.7 LLM + 0.3 RRF
    reranker_max_per_section: int = 2       # diversity cap
    reranker_content_truncate: int = 600    # chars sent to LLM per chunk

    model_config = {"env_prefix": "RETRIEVAL_", "extra": "ignore"}
```

This allows runtime tuning via env vars:
- `RETRIEVAL_RERANKER_ENABLED=false` — disable reranker (A/B testing)
- `RETRIEVAL_RERANKER_TOP_K=5` — final number of chunks passed to generation
- `RETRIEVAL_RERANKER_LLM_WEIGHT=0.7` — weight of LLM score in hybrid merge
- `RETRIEVAL_RERANKER_MAX_PER_SECTION=2` — diversity cap per section
- `RETRIEVAL_RERANKER_CONTENT_TRUNCATE=600` — chars per chunk sent to LLM

- [ ] **Step 2: Find the chat_service.py instantiation point**

Read `RAG/backend/services/chat_service.py`. Find the `ChatService.__init__` method — it instantiates `HybridRetriever`, `AsyncLLMClient`, and `ResponseJudge`. Add `LLMReranker` there.

Add import at the top of the file (after existing imports):
```python
from core.llm_reranker import LLMReranker
```

In `__init__`, after `self.retriever = ...` line, add:
```python
        self.reranker = LLMReranker()
```

- [ ] **Step 3: Insert rerank call in `query_stream` after retrieval**

In `query_stream` (or the equivalent streaming method), find the block ending around line 159:
```python
            except Exception as exc:
                logger.error("Retrieval failed: %s", exc)
                retrieval_results = []
```

Add immediately after this `except` block (before line 161 `if trace:`):
```python
            # Rerank: 3-dim LLM scoring → hybrid merge → diversity cap → top-K
            if retrieval_results:
                try:
                    retrieval_results = await self.reranker.rerank(
                        rewritten_query,
                        retrieval_results,
                        top_k=settings.retrieval.reranker_top_k,
                    )
                except Exception as exc:
                    logger.warning("Reranker failed: %s — using RRF results", exc)
```

- [ ] **Step 4: Add reranker span to LangFuse trace**

Find the existing trace span block after retrieval (around line 162-172):
```python
            if trace:
                try:
                    trace.span(
                        name="retrieval",
                        input={"query": rewritten_query, "top_k": settings.retrieval.top_k},
                        output={
                            "chunks_found": len(retrieval_results),
                            "top_scores": [round(r.score, 3) for r in retrieval_results[:3]] if retrieval_results else [],
                        },
                    )
                except Exception:
                    pass
```

Replace with:
```python
            if trace:
                try:
                    trace.span(
                        name="retrieval",
                        input={"query": rewritten_query, "top_k": settings.retrieval.top_k},
                        output={
                            "chunks_found": len(retrieval_results),
                            "reranker_enabled": settings.retrieval.reranker_enabled,
                            "reranker_top_k": settings.retrieval.reranker_top_k,
                            "top_scores": [round(r.score, 3) for r in retrieval_results[:3]] if retrieval_results else [],
                        },
                    )
                except Exception:
                    pass
```

- [ ] **Step 5: Rebuild Docker image and restart**

```bash
cd RAG
docker compose -f docker-compose-app.yml build rag-backend
docker compose -f docker-compose-app.yml up -d rag-backend
docker compose -f docker-compose-app.yml logs rag-backend --tail 20
```

Expected: container starts without import errors.

- [ ] **Step 6: Smoke test — send a chat query and check logs**

```bash
curl -s -X POST http://localhost:8000/api/chat/<chat_id>/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "test query"}' | head -5
```

In logs:
```bash
docker compose -f docker-compose-app.yml logs rag-backend --tail 30 | grep -i rerank
```

Expected log line (from `logger.info` in `rerank()`):
```
rerank query='test query' n_in=10 n_out=5 latency_ms=1842 fallback=False
```

To disable reranker temporarily: set `RETRIEVAL_RERANKER_ENABLED=false` in the app env and restart.

- [ ] **Step 7: Commit**

```bash
git add RAG/backend/config.py RAG/backend/services/chat_service.py
git commit -m "feat(rag): wire LLMReranker into chat_service — top-10 RRF → reranked top-5"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| LLM scores chunks on relevance + specificity + coverage | Task 1 ✅ (`_SYSTEM_PROMPT`, `ChunkScore.total = 0.5r + 0.2s + 0.3c`) |
| Pydantic validation of LLM output (rejects out-of-range values) | Task 1 ✅ (`ChunkScore` with `Field(ge=0, le=5)`) |
| Hybrid merge: 0.7 LLM + 0.3 RRF normalized | Task 1 ✅ (`_hybrid_merge`) |
| Diversity cap: max 2 chunks per (document_id, section_title) | Task 1 ✅ (`_apply_diversity`) |
| Content truncation: 600 chars per chunk in prompt | Task 1 ✅ (`r.content[:content_truncate]`) |
| Negative prompt instructions in system prompt | Task 1 ✅ (`Do NOT prioritize:` block in `_SYSTEM_PROMPT`) |
| Observability: latency + fallback flag logged per call | Task 1 ✅ (`logger.info` at end of `rerank()`) |
| Returns top-5 by default (configurable) | Task 2 ✅ (`reranker_top_k=5`) |
| Graceful fallback if LLM fails | Task 1 ✅ (`except` block returns `results[:top_k]`) |
| Disabled via env var | Task 2 ✅ (`RETRIEVAL_RERANKER_ENABLED=false`) |
| Inserted between retrieval and generation | Task 2 ✅ (after retrieval block in `chat_service.py`) |
| LangFuse trace updated | Task 2 ✅ (`reranker_enabled` + `reranker_top_k` in span) |
| All config knobs exposed as env vars | Task 2 ✅ (`RETRIEVAL_RERANKER_*` prefix) |
| Tests: 8 cases — sort order, top_k, fallback, disabled, empty, hybrid, diversity, pydantic | Task 1 ✅ |

**Type consistency:** `rerank()` takes `list[RetrievalResult]`, returns `list[RetrievalResult]` — same type as `retriever.search()` output. Chat service assigns result back to `retrieval_results` — consistent.

**Known trade-off:** Adds ~2-4s latency per query on local qwen3:1.7b. With OpenRouter Gemini Flash (if key set) this drops to ~1s. Acceptable for a RAG use case — users wait for full generation anyway.

---

## Deferred to v2

Explicitly excluded from this implementation and why:

| Feature | Reason deferred |
|---|---|
| **Token budget awareness** | Requires a tokenizer dependency per model; content truncation at 600 chars is a safe proxy for now |
| **Caching of reranker results** | Cache invalidation is complex (query + chunk set key); fallback latency is acceptable |
| **Cross-encoder abstraction** (`BaseReranker` interface) | YAGNI — we have one implementation; abstract when a second arrives |
| **Confidence score from LLM** | Self-reported confidence from small models (qwen3:1.7b) is unreliable; total score is a better proxy |
| **Retry strategy on parse failure** | Graceful fallback to RRF is already good; retry adds latency for marginal gain |
