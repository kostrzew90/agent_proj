"""
mcp-fs-vinhunter — write-capable MCP SSE for VIN OSINT/vinhunter/.

Tools:
    fs_write_file(path, content) — write file inside /vinhunter/
    fs_read_file(path)           — read file
    fs_list_dir(path)            — list directory
    git_checkout_branch(name)    — create+checkout branch (or checkout existing)
    git_commit(message)          — git add -A && git commit
    git_push(branch)             — push to origin
    git_status()                 — short git status
"""
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fs-vinhunter", host="0.0.0.0")

_ROOT = Path(os.environ.get("VINHUNTER_ROOT", "/vinhunter"))


def _safe_path(path: str) -> Path:
    """Resolve path inside _ROOT, raise ValueError if traversal detected."""
    target = (_ROOT / path.lstrip("/")).resolve()
    if not str(target).startswith(str(_ROOT.resolve())):
        raise ValueError(f"Path traversal rejected: {path}")
    return target


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (result.stdout + result.stderr).strip()


@mcp.tool()
def fs_write_file(path: str, content: str) -> str:
    """Write content to a file inside the VINhunter directory."""
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to {target}"


@mcp.tool()
def fs_read_file(path: str) -> str:
    """Read a file from the VINhunter directory."""
    return _safe_path(path).read_text(encoding="utf-8")


@mcp.tool()
def fs_list_dir(path: str = "") -> str:
    """List directory contents inside VINhunter."""
    target = _safe_path(path)
    items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    return "\n".join(
        f"{'F' if p.is_file() else 'D'} {p.name}" for p in items
    )


@mcp.tool()
def git_checkout_branch(branch_name: str) -> str:
    """Create and checkout a branch (checkout existing if already present)."""
    out = _git(["checkout", "-b", branch_name])
    if "already exists" in out or "fatal" in out:
        out = _git(["checkout", branch_name])
    return out


@mcp.tool()
def git_commit(message: str) -> str:
    """Stage all changes and commit."""
    _git(["add", "-A"])
    return _git(["commit", "-m", message])


@mcp.tool()
def git_push(branch: str) -> str:
    """Push branch to origin with upstream tracking."""
    return _git(["push", "-u", "origin", branch])


@mcp.tool()
def git_status() -> str:
    """Return short git status."""
    return _git(["status", "--short"])


if __name__ == "__main__":
    mcp.run(transport="sse")
