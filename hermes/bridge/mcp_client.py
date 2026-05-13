"""
mcp_client.py — MCP SDK SSE client for browser-mcp.
"""
from __future__ import annotations

import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

_DEFAULT_URL = os.environ.get(
    "MCP_BROWSER_URL", "http://browser-mcp:8000/sse"
)


class MCPClient:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or _DEFAULT_URL
        self._sse_cm = None
        self._sess_cm = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "MCPClient":
        self._sse_cm = sse_client(self._url)
        read, write = await self._sse_cm.__aenter__()
        self._sess_cm = ClientSession(read, write)
        self._session = await self._sess_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._sess_cm is not None:
            await self._sess_cm.__aexit__(exc_type, exc, tb)
        if self._sse_cm is not None:
            await self._sse_cm.__aexit__(exc_type, exc, tb)

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        assert self._session is not None, "MCPClient not entered"
        result = await self._session.call_tool(tool, args)
        parts = []
        for c in result.content:
            text = getattr(c, "text", None)
            if text is None:
                continue
            try:
                parts.append(json.loads(text))
            except Exception:
                parts.append(text)
        if len(parts) == 1:
            return parts[0]
        return parts
