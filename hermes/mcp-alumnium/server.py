"""
mcp-alumnium — AI-native E2E browser testing via alumnium + Playwright.

Tools:
    al_navigate(url)       — navigate to URL, return title
    al_do(action)          — perform natural-language browser action
    al_check(assertion)    — verify assertion → "true" or "false: <reason>"
    al_get(value_desc)     — extract value from current page
    al_screenshot()        — save screenshot to /audit/
"""
import asyncio
import os
import threading
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, Browser, Page

try:
    from alumnium import Aluminium as _Aluminium
except ImportError:
    _Aluminium = None  # type: ignore

mcp = FastMCP("alumnium", host="0.0.0.0")

_AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", "/audit"))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# Persistent event loop — keeps browser alive across tool calls
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()
# All tool calls are serialized on _loop — concurrent FastMCP requests queue their
# coroutines and execute one at a time, so globals _browser/_page/_al are safe
# without additional locking as long as all access goes through _run().

_browser: Browser | None = None
_page: Page | None = None
_al = None  # alumnium.Aluminium instance


def _run(coro, timeout: float = 60.0):
    """Submit coroutine to the persistent loop, block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


async def _ensure_session():
    """Initialize or recover Playwright + alumnium session."""
    global _browser, _page, _al

    try:
        page_closed = _page is None or _page.is_closed()
    except Exception:
        page_closed = True
        _page = None
    if page_closed:
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        _page = await _browser.new_page()
        _al = _Aluminium(_page)

    return _page, _al


@mcp.tool()
def al_navigate(url: str) -> str:
    """Navigate to a URL and return page title."""
    async def _do():
        page, _ = await _ensure_session()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        title = await page.title()
        return f"Navigated to {url} — title: {title}"

    return _run(_do())


@mcp.tool()
def al_do(action: str) -> str:
    """Perform a browser action described in natural language."""
    async def _do():
        _, al = await _ensure_session()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, al.do, action)
        return f"Done: {action}"

    return _run(_do(), timeout=90.0)


@mcp.tool()
def al_check(assertion: str) -> str:
    """
    Verify an assertion about the current page.
    Returns 'true' or 'false: <reason>'.
    """
    async def _do():
        _, al = await _ensure_session()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, al.check, assertion)
        if result:
            return "true"
        return f"false: {assertion}"

    return _run(_do(), timeout=60.0)


@mcp.tool()
def al_get(value_desc: str) -> str:
    """Extract a value from the current page described in natural language."""
    async def _do():
        _, al = await _ensure_session()
        loop = asyncio.get_event_loop()
        return str(await loop.run_in_executor(None, al.get, value_desc))

    return _run(_do(), timeout=60.0)


@mcp.tool()
def al_screenshot() -> str:
    """Take screenshot of current page and save to /audit/."""
    async def _do():
        page, _ = await _ensure_session()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = _AUDIT_DIR / f"alumnium-{ts}.png"
        await page.screenshot(path=str(path))
        return f"Screenshot saved: {path}"

    return _run(_do())


if __name__ == "__main__":
    mcp.run(transport="sse")
