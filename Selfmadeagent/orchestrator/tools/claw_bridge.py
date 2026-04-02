import os
import asyncio
import subprocess
from pathlib import Path
import httpx
from langfuse.decorators import observe

CLAW_CORE_URL = os.getenv("CLAW_CORE_URL", "http://claw-core:8080")
WORKSPACE = Path(os.getenv("WORKSPACE_PATH", "/workspace"))


async def _claw_available() -> bool:
    """Check if claw-core is reachable."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{CLAW_CORE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


# --- Python fallback implementations ---

def _py_read_file(path: str) -> str:
    target = WORKSPACE / path
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return target.read_text(encoding="utf-8")


def _py_write_file(path: str, content: str) -> str:
    target = WORKSPACE / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {path}"


def _py_edit_file(path: str, old_string: str, new_string: str) -> str:
    target = WORKSPACE / path
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    text = target.read_text(encoding="utf-8")
    if old_string not in text:
        raise ValueError(f"old_string not found in {path}")
    text = text.replace(old_string, new_string, 1)
    target.write_text(text, encoding="utf-8")
    return f"Edited {path}"


def _py_bash(command: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"


def _py_glob(pattern: str, path: str = ".") -> str:
    base = WORKSPACE / path
    matches = sorted(str(p.relative_to(WORKSPACE)) for p in base.glob(pattern))
    return "\n".join(matches) if matches else "No files matched"


def _py_grep(pattern: str, path: str = ".") -> str:
    cmd = f'grep -rn "{pattern}" {path} 2>/dev/null | head -50'
    return _py_bash(cmd, timeout=10)


# --- Public API ---

TOOL_HANDLERS = {
    "read_file": lambda args: _py_read_file(args["path"]),
    "write_file": lambda args: _py_write_file(args["path"], args["content"]),
    "edit_file": lambda args: _py_edit_file(args["path"], args["old_string"], args["new_string"]),
    "bash": lambda args: _py_bash(args["command"], args.get("timeout", 30)),
    "glob": lambda args: _py_glob(args["pattern"], args.get("path", ".")),
    "grep": lambda args: _py_grep(args["pattern"], args.get("path", ".")),
}


@observe(name="tool_execution")
async def execute_tool(tool_name: str, arguments: dict) -> str:
    """Execute a tool by name with given arguments.

    Currently uses Python fallback for all tools.
    Claw-core HTTP delegation will be added when claw-core
    implements the tool endpoints.
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return f"Unknown tool: {tool_name}"

    try:
        result = await asyncio.to_thread(handler, arguments)
        # Truncate very long outputs
        if len(result) > 10000:
            result = result[:10000] + f"\n... (truncated, {len(result)} total chars)"
        return result
    except Exception as e:
        return f"Tool error ({tool_name}): {e}"
