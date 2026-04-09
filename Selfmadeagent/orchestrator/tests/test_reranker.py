from memory.reranker import rerank_rrf


def test_empty():
    assert rerank_rrf([], []) == []


def test_semantic_only():
    sem = [{"chunk_id": 1, "content": "a"}, {"chunk_id": 2, "content": "b"}]
    result = rerank_rrf(sem, [], top_k=2)
    assert len(result) == 2
    assert result[0]["chunk_id"] == 1  # rank 1 gets higher score


def test_merge_dedup():
    sem = [{"chunk_id": 1, "content": "a"}]
    kw = [{"chunk_id": 1, "content": "a"}, {"chunk_id": 2, "content": "b"}]
    result = rerank_rrf(sem, kw, top_k=2)
    assert len(result) == 2
    # chunk_id 1 appears in both → highest score
    assert result[0]["chunk_id"] == 1


def test_weighted_score():
    sem = [{"chunk_id": 1, "content": "a", "confidence": 0.9, "verified": True}]
    result = rerank_rrf(sem, [], top_k=1)
    assert "rrf_score" in result[0]
    assert result[0]["rrf_score"] > 0
