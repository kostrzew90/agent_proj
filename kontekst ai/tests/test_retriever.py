"""Tests for retriever and prompt composer."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from ai_repo.core.reranker import rerank_rrf
from ai_repo.core.prompt_composer import PromptComposer


# ── Reranker tests ───────────────────────────────────────────────────────

class TestRerankerRRF:

    def test_combines_semantic_and_keyword(self):
        """RRF should combine and deduplicate results."""
        semantic = [
            {"chunk_id": 1, "content": "a", "path": "a.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.9},
            {"chunk_id": 2, "content": "b", "path": "b.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.8},
        ]
        keyword = [
            {"chunk_id": 2, "content": "b", "path": "b.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.7},
            {"chunk_id": 3, "content": "c", "path": "c.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.6},
        ]
        results = rerank_rrf(semantic, keyword, k=60, top_k=10)

        assert len(results) == 3
        # chunk_id=2 appears in both, should have highest RRF score
        assert results[0]["chunk_id"] == 2
        assert "rrf_score" in results[0]

    def test_graph_bonus_applied(self):
        """Items with graph_neighbors should get bonus score."""
        semantic = [
            {"chunk_id": 1, "content": "a", "path": "a.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.9,
             "graph_neighbors": [{"name": "X", "kind": "class", "file_path": "x.py", "edge_type": "import"}]},
        ]
        keyword = []
        results = rerank_rrf(semantic, keyword, k=60, top_k=10, graph_bonus=0.05)

        assert len(results) == 1
        # Score should be 1/(60+1) + 0.05 (graph bonus)
        expected = 1.0 / 61 + 0.05
        assert abs(results[0]["rrf_score"] - expected) < 0.001

    def test_respects_top_k(self):
        """Should return at most top_k results."""
        semantic = [
            {"chunk_id": i, "content": f"c{i}", "path": f"{i}.py", "type": "python",
             "start_line": 1, "end_line": 5, "score": 0.9 - i * 0.01}
            for i in range(20)
        ]
        results = rerank_rrf(semantic, [], top_k=5)
        assert len(results) == 5

    def test_empty_inputs(self):
        """Should handle empty inputs gracefully."""
        results = rerank_rrf([], [])
        assert results == []


# ── Retriever tests ──────────────────────────────────────────────────────

class TestRetriever:

    @pytest.mark.asyncio
    async def test_retrieve_pipeline(self, mock_db, mock_embeddings):
        """Test full retrieval pipeline with mocks."""
        mock_db.semantic_search.return_value = [
            {"chunk_id": 1, "content": "test code", "start_line": 1,
             "end_line": 5, "path": "test.py", "type": "python", "score": 0.9},
        ]
        mock_db.keyword_search.return_value = [
            {"chunk_id": 1, "content": "test code", "start_line": 1,
             "end_line": 5, "path": "test.py", "type": "python", "score": 0.7},
        ]

        # Mock the session context manager for _expand_with_graph and _log_retrieval
        session_mock = MagicMock()
        session_mock.query.return_value.filter_by.return_value.limit.return_value.all.return_value = []
        session_mock.add = MagicMock()
        session_mock.commit = MagicMock()
        mock_db.get_session.return_value.__enter__ = MagicMock(return_value=session_mock)
        mock_db.get_session.return_value.__exit__ = MagicMock(return_value=False)

        from ai_repo.core.retriever import Retriever
        retriever = Retriever(db=mock_db, embedding_client=mock_embeddings)

        results = await retriever.retrieve("test query", top_k=5)
        assert len(results) >= 1
        assert results[0]["chunk_id"] == 1


# ── PromptComposer tests ────────────────────────────────────────────────

class TestPromptComposer:

    def test_compose_basic(self, mock_db, sample_retrieval_results):
        """Test basic prompt composition."""
        composer = PromptComposer(db=mock_db)
        system, user = composer.compose("What is Database?", sample_retrieval_results)

        assert "code assistant" in system.lower()
        assert "What is Database?" in user
        assert "database.py" in user

    def test_compose_with_memory_facts(self, mock_db, sample_retrieval_results):
        """Test prompt includes memory facts."""
        facts = [
            {"key": "main_language", "value": "Python", "confidence": 0.9},
        ]
        composer = PromptComposer(db=mock_db)
        system, user = composer.compose("What language?", sample_retrieval_results, facts)

        assert "Project Facts" in user
        assert "main_language" in user
        assert "Python" in user

    def test_compose_with_graph_context(self, mock_db, sample_retrieval_results):
        """Test prompt includes graph neighbors."""
        composer = PromptComposer(db=mock_db)
        _, user = composer.compose("What uses Database?", sample_retrieval_results)

        assert "Related Symbols" in user
        assert "Indexer" in user
        assert "Retriever" in user

    def test_compose_empty_results(self, mock_db):
        """Test compose with no results."""
        composer = PromptComposer(db=mock_db)
        system, user = composer.compose("Hello?", [])

        assert "No context available" in user

    def test_format_risks_high_impact(self, mock_db):
        """Test risk detection for symbols referenced from 3+ files."""
        results = [
            {"path": f"file{i}.py", "graph_neighbors": [
                {"name": "shared_func", "kind": "function",
                 "file_path": "shared.py", "edge_type": "call"},
            ]}
            for i in range(4)
        ]
        composer = PromptComposer(db=mock_db)
        risk_text = composer._format_risks(results)
        assert "shared_func" in risk_text
        assert "4 files" in risk_text
