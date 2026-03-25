"""Plugin base classes and context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PluginContext:
    """Context passed to plugins during registration."""
    db: Any  # Database instance
    llm: Any = None  # LLMClient instance (optional)
    register_tool: Callable | None = None  # Callback to register MCP tools


class PluginBase(ABC):
    """Base class for all plugins."""

    @abstractmethod
    def register(self, context: PluginContext) -> dict[str, Callable]:
        """Register the plugin and return a dict of tool_name -> handler.

        Args:
            context: Plugin context with DB, LLM, and tool registration callback.

        Returns:
            Dict mapping tool names to their handler callables.
        """
        ...
