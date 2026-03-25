"""MCP tool registry — core tools + dynamic plugin tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """MCP tool definition."""
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable
    source: str = "core"  # "core" or plugin name


class ToolRegistry:
    """Registry for MCP tools — core + plugin-provided."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered MCP tool: {tool.name} (source: {tool.source})")

    def unregister(self, name: str):
        """Remove a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in MCP format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def __len__(self) -> int:
        return len(self._tools)


# Singleton registry
registry = ToolRegistry()
