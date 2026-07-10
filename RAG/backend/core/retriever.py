"""
RAG System — Hybrid Search Retriever
Combines pgvector cosine similarity (semantic) with PostgreSQL full-text search (BM25)
using Reciprocal Rank Fusion for result merging.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core.embeddings import AsyncEmbeddingClient

logger = logging.getLogger("rag.core.retriever")


@dataclass
class RetrievalResult:
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


class HybridRetriever:
    """
    Hybrid retriever combining semantic (pgvector) and BM25 (tsvector) search
    with Reciprocal Rank Fusion.
    """

    def __init__(
        self,
        embedding_client: Optional[AsyncEmbeddingClient] = None,
        semantic_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
    ):
        self._embedding_client = embedding_client
        self.semantic_weight = semantic_weight if semantic_weight is not None else settings.retrieval.semantic_weight
        self.bm25_weight = bm25_weight if bm25_weight is not None else settings.retrieval.bm25_weight

    def _get_embedding_client(self) -> AsyncEmbeddingClient:
        if self._embedding_client is not None:
            return self._embedding_client
        return AsyncEmbeddingClient(
            base_url=settings.ai.ollama_url,
            model=settings.ai.embedding_model,
        )

    async def search(
        self,
        query: str,
        db_session: AsyncSession,
        top_k: Optional[int] = None,
        folder_ids: Optional[list[int]] = None,
        tag_ids: Optional[list[int]] = None,
        document_ids: Optional[list[int]] = None,
    ) -> list[RetrievalResult]:
        """
        Main search method. Embeds the query, runs semantic and BM25 search in
        parallel, fuses results with RRF, and returns ranked RetrievalResults.

        Args:
            query: Natural-language query string.
            db_session: Async SQLAlchemy session.
            top_k: Number of results to return (defaults to settings.retrieval.top_k).
            folder_ids: Optional list of folder IDs to restrict search to.
            tag_ids: Optional list of tag IDs to restrict search to.

        Returns:
            List of RetrievalResult sorted by fused RRF score (descending).
        """
        if top_k is None:
            top_k = settings.retrieval.top_k

        # Fetch candidates from both sources (retrieve more than top_k for fusion)
        candidate_n = max(top_k * 3, 30)

        # Build optional document filter subquery params
        doc_filter = _DocFilter(folder_ids=folder_ids, tag_ids=tag_ids, document_ids=document_ids)

        # Embed query
        client = self._get_embedding_client()
        query_embedding = await client.embed_one(query)

        # Run both searches in parallel
        semantic_results, bm25_results = await asyncio.gather(
            self._semantic_search(query_embedding, db_session, candidate_n, doc_filter),
            self._bm25_search(query, db_session, candidate_n, doc_filter),
        )

        logger.debug(
            "Hybrid search: semantic=%d results, bm25=%d results",
            len(semantic_results),
            len(bm25_results),
        )

        # Fuse results
        fused = self._rrf_fusion(semantic_results, bm25_results)

        return fused[:top_k]

    async def _semantic_search(
        self,
        embedding: list[float],
        db: AsyncSession,
        top_n: int,
        doc_filter: "_DocFilter",
    ) -> list[RetrievalResult]:
        """
        pgvector cosine distance search. Lower distance = higher similarity.
        Returns results sorted by similarity descending (score = 1 - distance).
        """
        filter_joins, filter_where, filter_params = doc_filter.sql_parts()

        sql = text(
            f"""
            SELECT
                dc.id              AS chunk_id,
                dc.document_id,
                dc.content,
                dc.page_number,
                dc.section_title,
                dc.chunk_type,
                d.filename         AS document_name,
                1 - (dc.embedding <=> CAST(:query_vec AS vector)) AS similarity
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            {filter_joins}
            WHERE dc.embedding IS NOT NULL
              AND d.status = 'ready'
              {filter_where}
            ORDER BY dc.embedding <=> CAST(:query_vec AS vector)
            LIMIT :top_n
            """
        )

        params = {
            "query_vec": _vector_to_pg(embedding),
            "top_n": top_n,
            **filter_params,
        }

        result = await db.execute(sql, params)
        rows = result.mappings().all()

        return [
            RetrievalResult(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                content=row["content"],
                score=float(row["similarity"]),
                page_number=row["page_number"],
                section_title=row["section_title"],
                document_name=row["document_name"],
                chunk_type=row["chunk_type"] or "text",
                semantic_score=float(row["similarity"]),
                bm25_score=None,
            )
            for row in rows
        ]

    async def _bm25_search(
        self,
        query: str,
        db: AsyncSession,
        top_n: int,
        doc_filter: "_DocFilter",
    ) -> list[RetrievalResult]:
        """
        PostgreSQL full-text search using tsvector + ts_rank.
        Uses 'simple' config for language-agnostic matching.
        Returns results sorted by ts_rank descending.
        """
        filter_joins, filter_where, filter_params = doc_filter.sql_parts()

        sql = text(
            f"""
            SELECT
                dc.id              AS chunk_id,
                dc.document_id,
                dc.content,
                dc.page_number,
                dc.section_title,
                dc.chunk_type,
                d.filename         AS document_name,
                ts_rank(
                    to_tsvector('simple', dc.content),
                    plainto_tsquery('simple', :query)
                ) AS rank_score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            {filter_joins}
            WHERE to_tsvector('simple', dc.content) @@ plainto_tsquery('simple', :query)
              AND d.status = 'ready'
              {filter_where}
            ORDER BY rank_score DESC
            LIMIT :top_n
            """
        )

        params = {
            "query": query,
            "top_n": top_n,
            **filter_params,
        }

        result = await db.execute(sql, params)
        rows = result.mappings().all()

        return [
            RetrievalResult(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                content=row["content"],
                score=float(row["rank_score"]),
                page_number=row["page_number"],
                section_title=row["section_title"],
                document_name=row["document_name"],
                chunk_type=row["chunk_type"] or "text",
                semantic_score=None,
                bm25_score=float(row["rank_score"]),
            )
            for row in rows
        ]

    def _rrf_fusion(
        self,
        semantic_results: list[RetrievalResult],
        bm25_results: list[RetrievalResult],
        k: int = 60,
    ) -> list[RetrievalResult]:
        """
        Reciprocal Rank Fusion.
        score(chunk) = sum over sources of: 1 / (k + rank_in_source)
        Ranks start at 1.

        Merges metadata from both sources; retains both semantic_score and
        bm25_score for downstream transparency.
        """
        # chunk_id -> accumulated RRF score
        rrf_scores: dict[int, float] = {}
        # chunk_id -> best RetrievalResult so far (for metadata)
        best: dict[int, RetrievalResult] = {}
        # chunk_id -> individual scores
        semantic_score_map: dict[int, float] = {}
        bm25_score_map: dict[int, float] = {}

        for rank, result in enumerate(semantic_results, start=1):
            cid = result.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
            semantic_score_map[cid] = result.semantic_score or result.score
            if cid not in best:
                best[cid] = result

        for rank, result in enumerate(bm25_results, start=1):
            cid = result.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
            bm25_score_map[cid] = result.bm25_score or result.score
            if cid not in best:
                best[cid] = result

        # Sort by fused score descending
        sorted_ids = sorted(rrf_scores, key=lambda c: rrf_scores[c], reverse=True)

        fused: list[RetrievalResult] = []
        for cid in sorted_ids:
            base = best[cid]
            fused.append(
                RetrievalResult(
                    chunk_id=base.chunk_id,
                    document_id=base.document_id,
                    content=base.content,
                    score=rrf_scores[cid],
                    page_number=base.page_number,
                    section_title=base.section_title,
                    document_name=base.document_name,
                    chunk_type=base.chunk_type,
                    semantic_score=semantic_score_map.get(cid),
                    bm25_score=bm25_score_map.get(cid),
                )
            )

        return fused


# =============================================================
# Helpers
# =============================================================

class _DocFilter:
    """Encapsulates optional folder/tag filters and generates SQL fragments."""

    def __init__(
        self,
        folder_ids: Optional[list[int]] = None,
        tag_ids: Optional[list[int]] = None,
        document_ids: Optional[list[int]] = None,
    ):
        self.folder_ids = folder_ids or []
        self.tag_ids = tag_ids or []
        self.document_ids = document_ids or []

    def sql_parts(self) -> tuple[str, str, dict]:
        """
        Returns (join_clause, where_clause, params_dict).
        Both clauses are safe to embed directly into a parameterised query.
        """
        joins = []
        wheres = []
        params: dict = {}

        if self.folder_ids:
            joins.append(
                "JOIN document_folders df ON df.document_id = d.id"
            )
            # Use ANY(:folder_ids) for array binding
            wheres.append("df.folder_id = ANY(:folder_ids)")
            params["folder_ids"] = self.folder_ids

        if self.tag_ids:
            joins.append(
                "JOIN document_tags dt ON dt.document_id = d.id"
            )
            wheres.append("dt.tag_id = ANY(:tag_ids)")
            params["tag_ids"] = self.tag_ids

        if self.document_ids:
            wheres.append("d.id = ANY(:document_ids)")
            params["document_ids"] = self.document_ids

        join_clause = "\n".join(joins)
        where_clause = ("AND " + " AND ".join(wheres)) if wheres else ""

        return join_clause, where_clause, params


def _vector_to_pg(vec: list[float]) -> str:
    """Convert a Python list of floats to a PostgreSQL vector literal string."""
    return "[" + ",".join(str(v) for v in vec) + "]"


# =============================================================
# Module-level singleton helper
# =============================================================

_retriever: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """Return a shared HybridRetriever instance (lazy init)."""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
