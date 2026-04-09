"""Re-ranker — Reciprocal Rank Fusion (RRF) for combining search results."""

from __future__ import annotations


def rerank_rrf(
    semantic_results: list[dict],
    keyword_results: list[dict],
    k: int = 60,
    top_k: int = 10,
) -> list[dict]:
    """Combine semantic + keyword results using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each ranking list.
    """
    scores: dict[int, float] = {}
    items: dict[int, dict] = {}

    for rank, item in enumerate(semantic_results, start=1):
        cid = item.get("chunk_id") or item.get("id") or id(item)
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in items:
            items[cid] = item

    for rank, item in enumerate(keyword_results, start=1):
        cid = item.get("chunk_id") or item.get("id") or id(item)
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in items:
            items[cid] = item

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    results = []
    for cid in sorted_ids[:top_k]:
        item = items[cid].copy()
        item["rrf_score"] = scores[cid]
        results.append(item)

    return results
