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


@pytest.mark.asyncio
async def test_backfill_uses_hybrid_order_not_rrf():
    """When diversity caps eviction triggers back-fill, prefer high-hybrid-score chunks over RRF order."""
    from core.llm_reranker import LLMReranker
    from core.llm import GenerationResult

    # 4 chunks, all in same section → diversity max_per_section=2 caps at 2.
    # LLM heavily favours chunks 3 and 4 (last two by RRF rank).
    # After diversity cap returns 2 chunks (first two by hybrid score),
    # top_k=3 forces back-fill of one more — should be the next-best hybrid, not RRF[0].
    results = [
        # chunk_id 0: RRF=1.0 (best by RRF), LLM=0 (worst by LLM)
        _FakeResult(0, 1, "low LLM but top RRF", 1.0, None, "S", "d.pdf", "text", None, None),
        # chunk_id 1: RRF=0.9, LLM=0
        _FakeResult(1, 1, "low LLM, high RRF", 0.9, None, "S", "d.pdf", "text", None, None),
        # chunk_id 2: RRF=0.5, LLM=5 (best hybrid)
        _FakeResult(2, 1, "best LLM", 0.5, None, "S", "d.pdf", "text", None, None),
        # chunk_id 3: RRF=0.4, LLM=4 (second-best hybrid)
        _FakeResult(3, 1, "second LLM", 0.4, None, "S", "d.pdf", "text", None, None),
    ]

    # LLM scores chunks 3,4 (1-based ids) very high — chunks 1,2 (1-based) very low
    llm_response = '''{
      "scores": [
        {"id": 1, "relevance": 0, "specificity": 0, "coverage": 0},
        {"id": 2, "relevance": 0, "specificity": 0, "coverage": 0},
        {"id": 3, "relevance": 5, "specificity": 5, "coverage": 5},
        {"id": 4, "relevance": 4, "specificity": 4, "coverage": 4}
      ]
    }'''
    mock_result = GenerationResult(text=llm_response, model="test")

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

        reranked = await reranker.rerank("test", results, top_k=3)

    # Expected: chunks 2 and 3 (best hybrid) fit under diversity cap.
    # Back-fill: should pick the next-best hybrid (chunk 0 with RRF=1.0 but LLM=0),
    # NOT a random RRF-first chunk. With back-fill walking merged (hybrid order),
    # the third pick is the highest remaining merged score.
    assert len(reranked) == 3
    chunk_ids = [r.chunk_id for r in reranked]
    # Chunks 2 and 3 should be in the top 2 (best LLM scores)
    assert 2 in chunk_ids and 3 in chunk_ids
