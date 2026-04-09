"""Tool result evaluator — heuristic scoring + LLM judge."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


def heuristic_evaluate(tool_name: str, args: dict, result: str) -> float:
    """Fast, free heuristic evaluation of tool result. Returns 0.0-1.0."""
    # Generic error check
    if result.startswith("Tool error"):
        return 0.0

    if tool_name == "bash":
        if "Exit code:" in result:
            match = re.search(r"Exit code: (\d+)", result)
            if match and match.group(1) != "0":
                return 0.3
        if "command not found" in result.lower():
            return 0.3
        if "timed out" in result.lower():
            return 0.2
        return 1.0

    if tool_name == "read_file":
        if not result or result.strip() == "":
            return 0.5
        return 1.0

    if tool_name == "write_file":
        if "Written" in result:
            return 1.0
        return 0.3

    if tool_name == "edit_file":
        if "Edited" in result:
            return 1.0
        if "old_string not found" in result:
            return 0.0
        return 0.3

    if tool_name == "glob":
        if "No files matched" in result:
            return 0.5
        return 1.0

    if tool_name == "grep":
        if result.strip() == "":
            return 0.5
        return 1.0

    return 0.7  # Unknown tool, neutral score
