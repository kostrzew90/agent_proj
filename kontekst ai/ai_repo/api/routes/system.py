"""System routes — health check and stats."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ai_repo.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    db: bool
    ollama: bool


class StatsResponse(BaseModel):
    documents: int
    chunks: int
    symbols: int
    edges: int
    memory_facts: int
    chunks_with_embeddings: int


@router.get("/health", response_model=HealthResponse)
def health(request: Request):
    """Health check — verify DB and Ollama connectivity."""
    db_ok = False
    ollama_ok = False

    # Check DB
    try:
        db = request.app.state.db
        db.get_stats()
        db_ok = True
    except Exception:
        pass

    # Check Ollama
    try:
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{settings.ollama.url.rstrip('/')}/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return HealthResponse(status=status, db=db_ok, ollama=ollama_ok)


@router.get("/stats", response_model=StatsResponse)
def stats(request: Request, repo_id: str | None = None):
    """Get index statistics."""
    db = request.app.state.db
    return db.get_stats(repo_id=repo_id)
