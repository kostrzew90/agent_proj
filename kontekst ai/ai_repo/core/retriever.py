"""Dual retrieval — semantic (pgvector) + keyword (tsvector) + graph expansion."""

from __future__ import annotations

import logging
import time
from typing import Optional

from ai_repo.config import settings
from ai_repo.core.database import Database
from ai_repo.core.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class Retriever:
    """Two-pass retrieval: semantic + keyword search with graph expansion."""

    def __init__(
        self,
        db: Optional[Database] = None,
        embedding_client: Optional[EmbeddingClient] = None,
    ):
        self.db = db or Database()
        self.embedder = embedding_client or EmbeddingClient()
        self.cfg = settings.retrieval

    async def retrieve(
        self,
        query: str,
        repo_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """Run full retrieval pipeline: semantic + keyword + graph expansion.

        Returns list of chunk dicts with scores, sorted by relevance.
        """
        top_k = top_k or self.cfg.top_k
        start = time.time()

        # Pass A: Semantic search
        semantic_results = []
        embed_start = time.time()
        query_embedding = await self.embedder.embed_one(query)
        embedding_ms = (time.time() - embed_start) * 1000

        if query_embedding:
            semantic_results = self.db.semantic_search(
                embedding=query_embedding,
                top_n=self.cfg.semantic_top_n,
                repo_id=repo_id,
            )
            logger.debug(f"Semantic search: {len(semantic_results)} results")
        else:
            logger.warning("No embedding generated — skipping semantic search")

        # Pass B: Keyword search (BM25 via tsvector)
        keyword_results = self.db.keyword_search(
            query_text=query,
            top_n=self.cfg.keyword_top_n,
            repo_id=repo_id,
        )
        logger.debug(f"Keyword search: {len(keyword_results)} results")

        # Combine via RRF in reranker (imported separately)
        from ai_repo.core.reranker import rerank_rrf

        combined = rerank_rrf(
            semantic_results=semantic_results,
            keyword_results=keyword_results,
            k=self.cfg.rrf_k,
            top_k=top_k,
        )

        # Pass C: Graph expansion — for top results, add neighboring chunks
        if combined:
            combined = self._expand_with_graph(combined, repo_id)

        latency_ms = (time.time() - start) * 1000
        logger.info(
            f"Retrieval: {len(combined)} results in {latency_ms:.1f}ms "
            f"(semantic={len(semantic_results)}, keyword={len(keyword_results)})"
        )

        # Log retrieval for analytics
        self._log_retrieval(
            query, top_k, latency_ms,
            semantic_count=len(semantic_results),
            keyword_count=len(keyword_results),
            final_count=len(combined),
            embedding_ms=embedding_ms,
        )

        return combined[:top_k]

    def retrieve_sync(
        self,
        query: str,
        repo_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """Synchronous retrieval — uses sync embedding."""
        top_k = top_k or self.cfg.top_k
        start = time.time()

        semantic_results = []
        embed_start = time.time()
        query_embedding = self.embedder.embed_one_sync(query)
        embedding_ms = (time.time() - embed_start) * 1000

        if query_embedding:
            semantic_results = self.db.semantic_search(
                embedding=query_embedding,
                top_n=self.cfg.semantic_top_n,
                repo_id=repo_id,
            )

        keyword_results = self.db.keyword_search(
            query_text=query,
            top_n=self.cfg.keyword_top_n,
            repo_id=repo_id,
        )

        from ai_repo.core.reranker import rerank_rrf

        combined = rerank_rrf(
            semantic_results=semantic_results,
            keyword_results=keyword_results,
            k=self.cfg.rrf_k,
            top_k=top_k,
        )

        if combined:
            combined = self._expand_with_graph(combined, repo_id)

        latency_ms = (time.time() - start) * 1000
        self._log_retrieval(
            query, top_k, latency_ms,
            semantic_count=len(semantic_results),
            keyword_count=len(keyword_results),
            final_count=len(combined),
            embedding_ms=embedding_ms,
        )

        return combined[:top_k]

    def _expand_with_graph(
        self, results: list[dict], repo_id: Optional[str] = None
    ) -> list[dict]:
        """For top results, look up related symbols in the graph."""
        if self.cfg.graph_expansion_depth <= 0:
            return results

        try:
            # Find symbols in those files and get their neighbors
            for r in results[:5]:
                r["graph_neighbors"] = []
                # For each symbol in the file, get neighbors
                try:
                    with self.db.get_session() as session:
                        from ai_repo.core.database import Symbol
                        file_symbols = session.query(Symbol).filter_by(
                            file_path=r["path"], repo_id=repo_id
                        ).limit(10).all()

                        for sym in file_symbols:
                            neighbors = self.db.get_neighbors(
                                sym.id, depth=self.cfg.graph_expansion_depth
                            )
                            for n in neighbors:
                                if n["file_path"] != r["path"]:
                                    r["graph_neighbors"].append({
                                        "name": n["name"],
                                        "kind": n["kind"],
                                        "file_path": n["file_path"],
                                        "edge_type": n["edge_type"],
                                    })
                except Exception as e:
                    logger.debug(f"Graph expansion failed for {r['path']}: {e}")
                    # Continue without graph neighbors, don't fail the whole retrieval
                    pass

        except Exception as e:
            logger.warning(f"Graph expansion failed: {e}")
            # Return results without graph neighbors
            pass

        return results

    def _log_retrieval(
        self, query: str, top_k: int, latency_ms: float,
        semantic_count: int = 0, keyword_count: int = 0,
        final_count: int = 0, embedding_ms: float = 0,
    ):
        """Log retrieval for analytics."""
        try:
            from ai_repo.core.database import RetrievalLog
            with self.db.get_session() as session:
                log = RetrievalLog(
                    query=query,
                    topk=top_k,
                    latency_ms=latency_ms,
                    provider_used="semantic+keyword",
                    semantic_count=semantic_count,
                    keyword_count=keyword_count,
                    final_count=final_count,
                    embedding_ms=embedding_ms,
                )
                session.add(log)
                session.commit()
        except Exception as e:
            logger.debug(f"Failed to log retrieval: {e}")
