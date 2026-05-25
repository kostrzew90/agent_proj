# RAG LLM Reranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-based reranker between RRF retrieval and LLM generation that scores each chunk on relevance + specificity and returns the top-5 most useful chunks instead of the raw RRF top-10.

**Architecture:** New `LLMReranker` class in `core/llm_reranker.py` follows the same pattern as `ResponseJudge` — single async LLM call scoring all 10 chunks at once, returns sorted top-K. Wired into `chat_service.py` after retrieval, before prompt building. Disabled by env var (`RETRIEVAL_RERANKER_ENABLED=false`) for A/B testing. Graceful fallback: if LLM fails, returns original RRF results.

**Tech Stack:** Python 3.11, `AsyncLLMClient` (Ollama qwen3:1.7b) or `OpenRouterClient` (Gemini Flash), pydantic-settings, pytest + pytest-asyncio

---

## Files Created / Modified

| File | Action |
|------|--------|
| `RAG/backend/core/llm_reranker.py` | CREATE — `LLMReranker` class |
| `RAG/backend/tests/test_llm_reranker.py` | CREATE — unit tests |
| `RAG/backend/config.py` | MODIFY — add `reranker_enabled`, `reranker_top_k` to `RetrievalSettings` |
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
from unittest.mock import AsyncMock, patch, MagicMock
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


def _make_results(n: int):
    return [
        _FakeResult(
            chunk_id=i,
            document_id=1,
            content=f"chunk content {i}",
            score=1.0 / (i + 1),
            page_number=None,
            section_title=None,
            document_name="doc.pdf",
            chunk_type="text",
            semantic_score=None,
            bm25_score=None,
        )
        for i in range(n)
    ]


LLM_RESPONSE_OK = '''{
  "scores": [
    {"id": 1, "relevance": 5, "specificity": 4},
    {"id": 2, "relevance": 3, "specificity": 2},
    {"id": 3, "relevance": 4, "specificity": 5},
    {"id": 4, "relevance": 1, "specificity": 1},
    {"id": 5, "relevance": 2, "specificity": 3}
  ]
}'''


@pytest.mark.asyncio
async def test_rerank_sorts_by_score():
    """Chunks with higher LLM score come first."""
    from core.llm_reranker import LLMReranker, _parse_scores

    results = _make_results(5)
    scores = _parse_scores(LLM_RESPONSE_OK)
    # id=3 has relevance=4, specificity=5 → 0.6*4 + 0.4*5 = 4.4 (highest)
    # id=1 has relevance=5, specificity=4 → 0.6*5 + 0.4*4 = 4.6 (actually highest)
    # Expected order by total: id=1 (4.6) > id=3 (4.4) > id=2 (2.6) > id=5 (2.4) > id=4 (1.4)
    assert scores[0]["id"] == 1
    assert scores[1]["id"] == 3


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

        reranker = LLMReranker()
        reranker._client = AsyncMock()

        reranked = await reranker.rerank("test query", [], top_k=5)

    assert reranked == []
    reranker._client.generate.assert_not_called()
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
Scores retrieved chunks on relevance + specificity and returns top-K.
Single LLM call for all chunks — fast enough for interactive use.
"""

import json
import logging
import re
from dataclasses import dataclass

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

Respond with ONLY a JSON object, no explanation, no markdown:
{"scores": [{"id": <chunk_number>, "relevance": <0-5>, "specificity": <0-5>}, ...]}"""


def _parse_scores(text: str) -> list[dict]:
    """Extract and sort score list from LLM output by total score descending."""
    # Strip <think>...</think> blocks (qwen3 chain-of-thought)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    data = {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    scores = data.get("scores", [])

    def _total(s: dict) -> float:
        r = max(0.0, min(5.0, float(s.get("relevance", 0))))
        sp = max(0.0, min(5.0, float(s.get("specificity", 0))))
        return 0.6 * r + 0.4 * sp

    return sorted(scores, key=_total, reverse=True)


class LLMReranker:
    """
    Reranks RRF retrieval results using a fast LLM judge.
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
        Score and sort results by LLM-assessed relevance + specificity.
        Falls back to original RRF order on any error.
        """
        effective_top_k = top_k if top_k is not None else settings.retrieval.reranker_top_k

        if not results:
            return []

        if not settings.retrieval.reranker_enabled:
            return results[:effective_top_k]

        chunks_text = "\n\n".join(
            f"[{i + 1}] {r.content}" for i, r in enumerate(results)
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
            return results[:effective_top_k]

        if not ranked_scores:
            logger.warning("LLM reranker returned no scores — using RRF order")
            return results[:effective_top_k]

        # Map 1-based chunk ids back to results (LLM uses [1], [2], ...)
        index_map = {i + 1: r for i, r in enumerate(results)}
        reranked: list[RetrievalResult] = []
        seen: set[int] = set()
        for s in ranked_scores:
            chunk_id = s.get("id")
            if chunk_id in index_map and chunk_id not in seen:
                reranked.append(index_map[chunk_id])
                seen.add(chunk_id)
            if len(reranked) >= effective_top_k:
                break

        # Fill remaining slots from original order if LLM missed any chunks
        for r in results:
            if len(reranked) >= effective_top_k:
                break
            key = next(
                (k for k, v in index_map.items() if v.chunk_id == r.chunk_id),
                None,
            )
            if key not in seen:
                reranked.append(r)
                seen.add(key)

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
5 passed
```

If tests fail with import errors, ensure pytest is run from `RAG/backend/` so that `core/` is on the path. Add `sys.path.insert(0, ".")` at the top of the test file if needed.

- [ ] **Step 5: Commit**

```bash
git add RAG/backend/core/llm_reranker.py RAG/backend/tests/__init__.py RAG/backend/tests/test_llm_reranker.py
git commit -m "feat(rag): add LLMReranker — scores chunks on relevance+specificity before generation"
```

---

## Task 2: Config + chat_service.py integration

**Files:**
- Modify: `RAG/backend/config.py:73-78`
- Modify: `RAG/backend/services/chat_service.py`

- [ ] **Step 1: Add reranker settings to `RetrievalSettings` in `config.py`**

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

    model_config = {"env_prefix": "RETRIEVAL_", "extra": "ignore"}
```

This allows disabling reranker via env: `RETRIEVAL_RERANKER_ENABLED=false`
And tuning the final count: `RETRIEVAL_RERANKER_TOP_K=5`

- [ ] **Step 2: Find the chat_service.py instantiation point**

Read `RAG/backend/services/chat_service.py`. Find the `ChatService.__init__` method — it instantiates `HybridRetriever`, `AsyncLLMClient`, and `ResponseJudge`. Add `LLMReranker` there.

Find the `__init__` block (look for `self.retriever = HybridRetriever()`):

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
            # Rerank: score chunks on relevance+specificity, keep top-K
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

Expected: no errors. If reranker LLM call succeeds, you'll see it complete before the streaming starts.

To verify reranker is running: check that response latency is ~2-4s higher than before (one extra LLM call on qwen3:1.7b). To disable temporarily: set `RETRIEVAL_RERANKER_ENABLED=false` in the app env and restart.

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
| LLM scores chunks on relevance + specificity | Task 1 ✅ (`_SYSTEM_PROMPT`, `_parse_scores`) |
| Returns top-5 by default (configurable) | Task 1 ✅ (`reranker_top_k=5`) |
| Graceful fallback if LLM fails | Task 1 ✅ (`except` block returns `results[:top_k]`) |
| Disabled via env var | Task 2 ✅ (`RETRIEVAL_RERANKER_ENABLED=false`) |
| Inserted between retrieval and generation | Task 2 ✅ (after line ~159 in chat_service.py) |
| LangFuse trace updated | Task 2 ✅ (reranker_enabled + reranker_top_k in span) |
| Uses same model as judge (free, local) | Task 1 ✅ (`settings.ai.judge_model = "qwen3:1.7b"`) |
| Tests cover: sort order, top_k, fallback, disabled, empty | Task 1 ✅ (5 tests) |

**Type consistency:** `rerank()` takes `list[RetrievalResult]`, returns `list[RetrievalResult]` — same type as `retriever.search()` output. Chat service assigns result back to `retrieval_results` — consistent.

**Known trade-off:** Adds ~2-4s latency per query on local qwen3:1.7b. With OpenRouter Gemini Flash (if key set) this drops to ~1s. Acceptable for a RAG use case — users wait for full generation anyway.
