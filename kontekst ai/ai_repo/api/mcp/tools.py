"""Core MCP tools — search, graph, memory operations."""

from __future__ import annotations

import logging
from typing import Any

from ai_repo.api.mcp.registry import ToolDefinition, registry
from ai_repo.core.database import Database

logger = logging.getLogger(__name__)


def register_core_tools(db: Database):
    """Register all core MCP tools with the registry."""

    # ── repo.search ──────────────────────────────────────────────────

    def search_handler(args: dict[str, Any]) -> dict:
        query = args["query"]
        top_k = args.get("top_k", 10)
        repo_id = args.get("repo_id", "default")

        from ai_repo.core.retriever import Retriever
        retriever = Retriever(db=db)
        results = retriever.retrieve_sync(query, repo_id=repo_id, top_k=top_k)

        return {
            "results": [
                {
                    "path": r["path"],
                    "start_line": r.get("start_line"),
                    "end_line": r.get("end_line"),
                    "content": r["content"][:500],
                    "score": r.get("rrf_score", r.get("score", 0)),
                }
                for r in results
            ]
        }

    registry.register(ToolDefinition(
        name="repo.search",
        description="Search the indexed repository using semantic + keyword retrieval.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results", "default": 10},
                "repo_id": {"type": "string", "description": "Repository ID", "default": "default"},
            },
            "required": ["query"],
        },
        handler=search_handler,
    ))

    # ── repo.graph_neighbors ─────────────────────────────────────────

    def graph_neighbors_handler(args: dict[str, Any]) -> dict:
        symbol = args["symbol"]
        depth = args.get("depth", 1)
        repo_id = args.get("repo_id")

        symbols = db.get_symbol_by_name(symbol, repo_id=repo_id)
        if not symbols:
            return {"error": f"Symbol '{symbol}' not found"}

        all_neighbors = []
        seen = set()
        for sym in symbols:
            for n in db.get_neighbors(sym.id, depth=depth):
                if n["id"] not in seen:
                    seen.add(n["id"])
                    all_neighbors.append(n)

        return {"symbol": symbol, "neighbors": all_neighbors}

    registry.register(ToolDefinition(
        name="repo.graph_neighbors",
        description="Get neighboring symbols in the code graph.",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name"},
                "depth": {"type": "integer", "description": "Traversal depth", "default": 1},
                "repo_id": {"type": "string", "description": "Repository ID"},
            },
            "required": ["symbol"],
        },
        handler=graph_neighbors_handler,
    ))

    # ── repo.impact_analysis ─────────────────────────────────────────

    def impact_handler(args: dict[str, Any]) -> dict:
        symbol = args["symbol"]
        depth = args.get("depth", 2)
        repo_id = args.get("repo_id")

        symbols = db.get_symbol_by_name(symbol, repo_id=repo_id)
        if not symbols:
            return {"error": f"Symbol '{symbol}' not found"}

        all_impact = []
        seen = set()
        for sym in symbols:
            for n in db.get_impact(sym.id, depth=depth):
                if n["id"] not in seen:
                    seen.add(n["id"])
                    all_impact.append(n)

        return {"symbol": symbol, "dependents": all_impact}

    registry.register(ToolDefinition(
        name="repo.impact_analysis",
        description="Get symbols that depend on this symbol (reverse dependency analysis).",
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol name"},
                "depth": {"type": "integer", "description": "Traversal depth", "default": 2},
                "repo_id": {"type": "string", "description": "Repository ID"},
            },
            "required": ["symbol"],
        },
        handler=impact_handler,
    ))

    # ── repo.memory_get ──────────────────────────────────────────────

    def memory_get_handler(args: dict[str, Any]) -> dict:
        from ai_repo.core.memory import MemoryManager
        mm = MemoryManager(db=db)

        key = args.get("key")
        if key:
            fact = mm.get_fact(key)
            return {"fact": fact} if fact else {"error": f"Fact '{key}' not found"}
        else:
            return {"facts": mm.get_all_facts()}

    registry.register(ToolDefinition(
        name="repo.memory_get",
        description="Get project memory facts. Pass a key for a specific fact, or omit for all.",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Fact key (optional)"},
            },
        },
        handler=memory_get_handler,
    ))

    # ── repo.memory_set ──────────────────────────────────────────────

    def memory_set_handler(args: dict[str, Any]) -> dict:
        from ai_repo.core.memory import MemoryManager
        mm = MemoryManager(db=db)

        fact = mm.set_fact(
            key=args["key"],
            value=args["value"],
            tags=args.get("tags", []),
            source=args.get("source", "mcp"),
        )
        return {"status": "ok", "fact": fact}

    registry.register(ToolDefinition(
        name="repo.memory_set",
        description="Set a project memory fact (key-value with optional tags).",
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Fact key"},
                "value": {"type": "string", "description": "Fact value"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "source": {"type": "string", "description": "Source identifier"},
            },
            "required": ["key", "value"],
        },
        handler=memory_set_handler,
    ))

    logger.info(f"Registered {len(registry)} core MCP tools")
