"""Test fixtures — mock DB, LLM, embeddings."""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

import pytest


@pytest.fixture
def mock_db():
    """Mock Database with common methods."""
    db = MagicMock()
    db.get_session.return_value.__enter__ = MagicMock()
    db.get_session.return_value.__exit__ = MagicMock(return_value=False)
    db.semantic_search.return_value = []
    db.keyword_search.return_value = []
    db.get_neighbors.return_value = []
    db.get_impact.return_value = []
    db.get_symbol_by_name.return_value = []
    db.get_stats.return_value = {
        "documents": 0, "chunks": 0, "symbols": 0,
        "edges": 0, "memory_facts": 0, "chunks_with_embeddings": 0,
    }
    return db


@pytest.fixture
def mock_llm():
    """Mock LLMClient."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="Mock LLM response")
    llm.generate_stream = AsyncMock()
    return llm


@pytest.fixture
def mock_embeddings():
    """Mock EmbeddingClient that returns fixed vectors."""
    embedder = MagicMock()
    fake_vector = [0.1] * 768
    embedder.embed_one = AsyncMock(return_value=fake_vector)
    embedder.embed_one_sync = MagicMock(return_value=fake_vector)
    embedder.embed_batch = AsyncMock(return_value=[fake_vector])
    embedder.embed_batch_sync = MagicMock(return_value=[fake_vector])
    return embedder


@pytest.fixture
def sample_retrieval_results():
    """Sample retrieval results for testing prompt_composer."""
    return [
        {
            "chunk_id": 1,
            "content": "class Database:\n    def __init__(self):\n        pass",
            "path": "ai_repo/core/database.py",
            "type": "python",
            "start_line": 128,
            "end_line": 134,
            "score": 0.95,
            "rrf_score": 0.0456,
            "graph_neighbors": [
                {"name": "Indexer", "kind": "class", "file_path": "ai_repo/core/indexer.py", "edge_type": "import"},
                {"name": "Retriever", "kind": "class", "file_path": "ai_repo/core/retriever.py", "edge_type": "import"},
            ],
        },
        {
            "chunk_id": 2,
            "content": "def get_stats(self):\n    return {}",
            "path": "ai_repo/core/database.py",
            "type": "python",
            "start_line": 400,
            "end_line": 420,
            "score": 0.85,
            "rrf_score": 0.0321,
            "graph_neighbors": [],
        },
    ]
