"""MCP server — exposes tools via HTTP endpoints compatible with MCP protocol."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ai_repo.api.mcp.registry import registry

logger = logging.getLogger(__name__)

router = APIRouter()

_initialized = False


def _ensure_initialized(request: Request):
    """Lazy-init core tools on first request."""
    global _initialized
    if not _initialized:
        from ai_repo.api.mcp.tools import register_core_tools
        register_core_tools(request.app.state.db)
        _initialized = True


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


class ToolCallResponse(BaseModel):
    content: list[dict[str, Any]]
    isError: bool = False


@router.get("/tools/list")
def list_tools(request: Request):
    """List all available MCP tools."""
    _ensure_initialized(request)
    return {"tools": registry.list_tools()}


@router.post("/tools/call", response_model=ToolCallResponse)
def call_tool(body: ToolCallRequest, request: Request):
    """Call an MCP tool by name with arguments."""
    _ensure_initialized(request)

    tool = registry.get(body.name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{body.name}' not found")

    try:
        result = tool.handler(body.arguments)
        return ToolCallResponse(
            content=[{"type": "text", "text": json.dumps(result, default=str)}],
        )
    except Exception as e:
        logger.error(f"MCP tool error ({body.name}): {e}")
        return ToolCallResponse(
            content=[{"type": "text", "text": json.dumps({"error": str(e)})}],
            isError=True,
        )
