"""
RAG System — Embedding Benchmark Tasks (FAZA 7.1)
Celery tasks for benchmarking embedding models against a test set.
"""

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Test set path (JSON file with questions + expected doc matches)
TEST_SET_PATH = Path(__file__).parent.parent / "benchmark_testset.json"

"""
Test set format (benchmark_testset.json):
[
    {
        "query": "What are the terms of contract termination?",
        "language": "en",
        "expected_doc_ids": [5, 12],       # document IDs that should appear in results
        "expected_chunk_ids": [45, 67, 89]  # optional: specific chunk IDs
    },
    ...
]
"""


# =============================================================
# Metric helpers
# =============================================================

def _recall_at_k(retrieved_ids: list[int], relevant_ids: list[int], k: int) -> float:
    """Recall@K: fraction of relevant docs found in top-K results."""
    if not relevant_ids:
        return 0.0
    # Deduplicate while preserving order (multiple chunks from same doc count once)
    seen = set()
    unique_ids = []
    for rid in retrieved_ids:
        if rid not in seen:
            seen.add(rid)
            unique_ids.append(rid)
    top_k = set(unique_ids[:k])
    hits = sum(1 for rid in relevant_ids if rid in top_k)
    return hits / len(relevant_ids)


def _mrr(retrieved_ids: list[int], relevant_ids: list[int]) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant result (rank is 1-based)."""
    relevant_set = set(relevant_ids)
    seen: set[int] = set()
    rank = 0
    for rid in retrieved_ids:
        if rid not in seen:
            seen.add(rid)
            rank += 1
            if rid in relevant_set:
                return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved_ids: list[int], relevant_ids: list[int], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K.

    Assumes binary relevance: a retrieved ID is either relevant (gain=1) or not (gain=0).
    """
    if not relevant_ids:
        return 0.0

    relevant_set = set(relevant_ids)
    top_k = retrieved_ids[:k]

    # DCG: gain only for FIRST occurrence of each relevant doc
    seen: set[int] = set()
    dcg = 0.0
    for rank, rid in enumerate(top_k, start=1):
        if rid in relevant_set and rid not in seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen.add(rid)

    # Ideal DCG: best possible ordering — all relevant docs at the top
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

    return dcg / idcg if idcg > 0 else 0.0


# =============================================================
# Sync retrieval helper (direct SQL — no async needed in Celery)
# =============================================================

def _vector_to_pg(vec: list[float]) -> str:
    """Convert a Python list of floats to a PostgreSQL vector literal string."""
    return "[" + ",".join(str(v) for v in vec) + "]"


def _semantic_search_sync(
    embedding: list[float],
    session,
    top_k: int,
) -> list[dict]:
    """Run pgvector cosine similarity search synchronously.

    Returns list of dicts with keys: chunk_id, document_id, similarity.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT
            dc.id            AS chunk_id,
            dc.document_id,
            1 - (dc.embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.embedding IS NOT NULL
          AND d.status = 'ready'
        ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
        LIMIT :top_k
        """
    )

    result = session.execute(
        sql,
        {"query_vec": _vector_to_pg(embedding), "top_k": top_k},
    )
    rows = result.mappings().all()
    return [
        {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "similarity": float(row["similarity"]),
        }
        for row in rows
    ]


# =============================================================
# Celery task
# =============================================================

@celery_app.task(name="benchmark.run_embedding_benchmark", bind=True)
def run_embedding_benchmark(
    self,
    model_name: Optional[str] = None,
    notes: str = "",
) -> dict:
    """Run full benchmark for an embedding model.

    If model_name is None, benchmarks the currently configured model.

    Steps:
    1. Load test set from JSON
    2. For each query: embed it, run cosine similarity search, measure latency
    3. Compute per-query metrics against expected_doc_ids
    4. Aggregate: Recall@5, Recall@10, MRR, nDCG@10
    5. Persist results to embedding_benchmarks table
    6. Return summary dict

    Args:
        model_name: Ollama model name to benchmark. None => settings.ai.embedding_model.
        notes: Free-text note stored alongside results.

    Returns:
        dict with keys: model_name, model_dimension, recall_at_5, recall_at_10,
        mrr, ndcg_at_10, avg_latency_ms, test_set_size, notes, benchmark_id.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from config import settings
    from core.database import EmbeddingBenchmark
    from core.embeddings import EmbeddingClient

    # ------------------------------------------------------------------
    # 1. Load test set
    # ------------------------------------------------------------------
    if not TEST_SET_PATH.exists():
        raise FileNotFoundError(
            f"Benchmark test set not found at {TEST_SET_PATH}. "
            "Create benchmark_testset.json in the backend directory."
        )

    with open(TEST_SET_PATH, encoding="utf-8") as fh:
        test_cases = json.load(fh)

    if not test_cases:
        raise ValueError("benchmark_testset.json is empty — add at least one test case.")

    logger.info("Loaded %d test cases from %s", len(test_cases), TEST_SET_PATH)

    # ------------------------------------------------------------------
    # 2. Initialise embedding client
    # ------------------------------------------------------------------
    effective_model = model_name or settings.ai.embedding_model

    embedding_client = EmbeddingClient(model=effective_model)
    logger.info("Benchmarking model: %s", effective_model)

    # ------------------------------------------------------------------
    # 3. Run retrieval for each query
    # ------------------------------------------------------------------
    recalls_at_5: list[float] = []
    recalls_at_10: list[float] = []
    mrrs: list[float] = []
    ndcgs_at_10: list[float] = []
    latencies_ms: list[float] = []

    # Sync SQLAlchemy engine (psycopg2)
    sync_engine = create_engine(settings.database.url, pool_pre_ping=True)

    vector_dimension: Optional[int] = None

    with Session(sync_engine) as db_session:
        for idx, case in enumerate(test_cases):
            query: str = case["query"]
            expected_doc_ids: list[int] = case.get("expected_doc_ids", [])

            if not expected_doc_ids:
                logger.warning(
                    "Test case %d has no expected_doc_ids — skipping metric calculation.",
                    idx,
                )

            # Embed the query and measure latency
            t0 = time.perf_counter()
            try:
                query_embedding = embedding_client.embed_one(query)
            except Exception as exc:
                logger.error("Failed to embed query %d ('%s'): %s", idx, query[:80], exc)
                raise

            latency_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(latency_ms)

            # Capture dimension from first embedding
            if vector_dimension is None:
                vector_dimension = len(query_embedding)

            # Retrieve top-10 chunks by cosine similarity
            try:
                results = _semantic_search_sync(query_embedding, db_session, top_k=10)
            except Exception as exc:
                logger.error("DB retrieval failed for query %d: %s", idx, exc)
                raise

            retrieved_doc_ids = [r["document_id"] for r in results]

            # Compute per-query metrics
            if expected_doc_ids:
                recalls_at_5.append(_recall_at_k(retrieved_doc_ids, expected_doc_ids, k=5))
                recalls_at_10.append(_recall_at_k(retrieved_doc_ids, expected_doc_ids, k=10))
                mrrs.append(_mrr(retrieved_doc_ids, expected_doc_ids))
                ndcgs_at_10.append(_ndcg_at_k(retrieved_doc_ids, expected_doc_ids, k=10))

            logger.debug(
                "Query %d/%d | latency=%.1f ms | recall@5=%.3f | recall@10=%.3f",
                idx + 1,
                len(test_cases),
                latency_ms,
                recalls_at_5[-1] if recalls_at_5 else 0.0,
                recalls_at_10[-1] if recalls_at_10 else 0.0,
            )

    embedding_client.close()

    # ------------------------------------------------------------------
    # 4. Aggregate metrics
    # ------------------------------------------------------------------
    def _avg(values: list[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    avg_recall_5 = _avg(recalls_at_5)
    avg_recall_10 = _avg(recalls_at_10)
    avg_mrr = _avg(mrrs)
    avg_ndcg = _avg(ndcgs_at_10)
    avg_latency = _avg(latencies_ms)

    logger.info(
        "Benchmark complete | model=%s | R@5=%.4f | R@10=%.4f | MRR=%.4f | nDCG@10=%.4f | avg_latency=%.1f ms",
        effective_model,
        avg_recall_5 or 0.0,
        avg_recall_10 or 0.0,
        avg_mrr or 0.0,
        avg_ndcg or 0.0,
        avg_latency or 0.0,
    )

    # ------------------------------------------------------------------
    # 5. Persist to DB
    # ------------------------------------------------------------------
    benchmark_id: Optional[int] = None

    try:
        with Session(sync_engine) as save_session:
            record = EmbeddingBenchmark(
                model_name=effective_model,
                model_dimension=vector_dimension,
                recall_at_5=avg_recall_5,
                recall_at_10=avg_recall_10,
                mrr=avg_mrr,
                ndcg_at_10=avg_ndcg,
                avg_latency_ms=avg_latency,
                test_set_size=len(test_cases),
                notes=notes or None,
            )
            save_session.add(record)
            save_session.commit()
            save_session.refresh(record)
            benchmark_id = record.id
            logger.info("Saved benchmark result with id=%d", benchmark_id)
    except Exception as exc:
        logger.error("Failed to save benchmark result to DB: %s", exc)
        # Do not re-raise — return metrics even if DB write fails

    # ------------------------------------------------------------------
    # 6. Return summary
    # ------------------------------------------------------------------
    return {
        "benchmark_id": benchmark_id,
        "model_name": effective_model,
        "model_dimension": vector_dimension,
        "recall_at_5": avg_recall_5,
        "recall_at_10": avg_recall_10,
        "mrr": avg_mrr,
        "ndcg_at_10": avg_ndcg,
        "avg_latency_ms": avg_latency,
        "test_set_size": len(test_cases),
        "evaluated_cases": len(recalls_at_5),  # cases that had expected_doc_ids
        "notes": notes,
    }
