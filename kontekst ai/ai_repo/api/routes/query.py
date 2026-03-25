"""Query route — RAG pipeline endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    repo_id: str = "default"
    top_k: int = Field(default=10, ge=1, le=50)


class SourceItem(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None
    score: float = 0.0


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    latency_ms: float


@router.post("", response_model=QueryResponse)
async def run_query(req: QueryRequest, request: Request):
    """Run the full RAG pipeline: retrieve -> compose -> LLM -> response."""
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"[/query] Request received: {req.query[:50]}")
    start = time.time()
    db = request.app.state.db
    logger.info("[/query] DB acquired")

    from ai_repo.core.embeddings import EmbeddingClient
    from ai_repo.core.llm import LLMClient
    from ai_repo.core.memory import MemoryManager
    from ai_repo.core.prompt_composer import PromptComposer
    from ai_repo.core.retriever import Retriever

    logger.info("[/query] Creating components")
    retriever = Retriever(db=db, embedding_client=EmbeddingClient())
    composer = PromptComposer(db=db)
    llm = LLMClient(db=db, purpose="query")
    memory = MemoryManager(db=db)

    # Retrieve
    logger.info("[/query] Starting retrieval (SYNC)")
    # USE SYNC VERSION TO AVOID ASYNCIO EVENT LOOP ISSUES WITH CHAINLIT
    results = retriever.retrieve_sync(req.query, repo_id=req.repo_id, top_k=req.top_k)
    logger.info(f"[/query] Retrieval done: {len(results)} results")

    # Memory facts
    facts = memory.search_facts(query=req.query)

    # Compose prompt
    system_prompt, user_prompt = composer.compose(req.query, results, facts)

    # Generate answer
    answer = await llm.generate(prompt=user_prompt, system=system_prompt)

    # Build sources
    sources = [
        SourceItem(
            path=r["path"],
            start_line=r.get("start_line"),
            end_line=r.get("end_line"),
            score=r.get("rrf_score", r.get("score", 0)),
        )
        for r in results
    ]

    latency_ms = (time.time() - start) * 1000
    return QueryResponse(answer=answer, sources=sources, latency_ms=latency_ms)
