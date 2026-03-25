"""Re-ranker — Reciprocal Rank Fusion (RRF) for combining search results."""

from __future__ import annotations


def rerank_rrf(
    semantic_results: list[dict],
    keyword_results: list[dict],
    k: int = 60,
    top_k: int = 10,
    graph_bonus: float = 0.05,
) -> list[dict]:
    """Combine semantic + keyword results using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each ranking list where the item appears.

    Args:
        semantic_results: Results from vector similarity search.
        keyword_results: Results from BM25/tsvector search.
        k: RRF constant (default 60 — standard value from the paper).
        top_k: Number of results to return.
        graph_bonus: Extra score for items that appear in graph neighbors.

    Returns:
        Merged list of results sorted by RRF score, deduplicated by chunk_id.
    """
    scores: dict[int, float] = {}  # chunk_id → rrf_score
    items: dict[int, dict] = {}    # chunk_id → result dict

    # Semantic ranking
    for rank, item in enumerate(semantic_results, start=1):
        cid = item["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in items:
            items[cid] = item

    # Keyword ranking
    for rank, item in enumerate(keyword_results, start=1):
        cid = item["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in items:
            items[cid] = item

    # Graph neighbor bonus — items that have graph context get a small boost
    for cid, item in items.items():
        if item.get("graph_neighbors"):
            scores[cid] += graph_bonus

    # Sort by score descending
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    results = []
    for cid in sorted_ids[:top_k]:
        item = items[cid].copy()
        item["rrf_score"] = scores[cid]
        results.append(item)

    return results
