"""Memory routes — CRUD for project facts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter()


class FactCreate(BaseModel):
    key: str
    value: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    source: str | None = None


class FactResponse(BaseModel):
    id: int
    key: str
    value: str
    confidence: float
    tags: list[str]
    source: str | None
    updated_at: str | None


@router.get("", response_model=list[FactResponse])
def list_facts(
    request: Request,
    tag: str | None = Query(default=None, description="Filter by tag"),
    q: str | None = Query(default=None, description="Search query"),
):
    """List or search memory facts."""
    from ai_repo.core.memory import MemoryManager

    mm = MemoryManager(db=request.app.state.db)

    if q or tag:
        tags = [tag] if tag else None
        return mm.search_facts(query=q or "", tags=tags)
    return mm.get_all_facts()


@router.post("", response_model=FactResponse)
def create_fact(body: FactCreate, request: Request):
    """Create or update a memory fact."""
    from ai_repo.core.memory import MemoryManager

    mm = MemoryManager(db=request.app.state.db)
    return mm.set_fact(
        key=body.key,
        value=body.value,
        confidence=body.confidence,
        tags=body.tags,
        source=body.source,
    )


@router.delete("/{key}")
def delete_fact(key: str, request: Request):
    """Delete a memory fact by key."""
    from ai_repo.core.memory import MemoryManager

    mm = MemoryManager(db=request.app.state.db)
    if not mm.delete_fact(key):
        raise HTTPException(status_code=404, detail=f"Fact '{key}' not found")
    return {"status": "deleted", "key": key}
