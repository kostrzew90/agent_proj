"""Graph routes — symbol neighbors and impact analysis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()


class NeighborItem(BaseModel):
    id: int
    name: str
    kind: str
    file_path: str
    start_line: int | None = None
    edge_type: str
    depth: int


@router.get("/neighbors/{symbol_name}", response_model=list[NeighborItem])
def get_neighbors(
    symbol_name: str,
    request: Request,
    depth: int = Query(default=1, ge=1, le=5),
    repo_id: str | None = Query(default=None),
):
    """Get neighboring symbols in the code graph."""
    db = request.app.state.db
    symbols = db.get_symbol_by_name(symbol_name, repo_id=repo_id)

    if not symbols:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol_name}' not found")

    all_neighbors: list[dict] = []
    seen_ids: set[int] = set()
    for sym in symbols:
        for n in db.get_neighbors(sym.id, depth=depth):
            if n["id"] not in seen_ids:
                seen_ids.add(n["id"])
                all_neighbors.append(n)

    return all_neighbors


@router.get("/impact/{symbol_name}", response_model=list[NeighborItem])
def get_impact(
    symbol_name: str,
    request: Request,
    depth: int = Query(default=2, ge=1, le=5),
    repo_id: str | None = Query(default=None),
):
    """Get symbols that depend on this symbol (reverse dependency / impact)."""
    db = request.app.state.db
    symbols = db.get_symbol_by_name(symbol_name, repo_id=repo_id)

    if not symbols:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol_name}' not found")

    all_impact: list[dict] = []
    seen_ids: set[int] = set()
    for sym in symbols:
        for n in db.get_impact(sym.id, depth=depth):
            if n["id"] not in seen_ids:
                seen_ids.add(n["id"])
                all_impact.append(n)

    return all_impact
