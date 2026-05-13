"""
llm_client.py — Thin wrapper around hermes-llm-proxy (FastMCP SSE).

Reuses the same MCPClient SSE pattern as mcp_client.py / browser-mcp.

Public API:
    call_llm(prompt, tier="medium", system_prompt=None, max_tokens=1024) -> dict

Return dict keys:
    text       str   — LLM response text (empty string on error)
    model      str   — model that produced the response (or "" on error)
    tier       str   — tier used
    latency_ms int   — wall-clock milliseconds
    error      str|None — error description, None on success
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

_LLM_PROXY_URL: str = os.environ.get(
    "LLM_PROXY_URL", "http://hermes-llm-proxy:8000/sse"
)

# Tier → timeout (seconds)
_TIMEOUTS: dict[str, float] = {
    "easy": 60.0,
    "medium": 120.0,
    "hard": 300.0,
}

_RETRYABLE_ERRORS = ("timed out", "timeout", "connectionerror", "connection error", "unreachable", "connect")


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _RETRYABLE_ERRORS)


async def _call_ask_auto(
    prompt: str,
    tier: str,
    system_prompt: str | None,
    max_tokens: int,
    timeout: float,
    skill: str | None = None,
) -> dict[str, Any]:
    """Call ask_auto on hermes-llm-proxy via SSE MCP. Returns raw result dict."""
    args: dict[str, Any] = {
        "prompt": prompt,
        "complexity": tier,
        "max_tokens": max_tokens,
    }
    if system_prompt is not None:
        args["system_prompt"] = system_prompt
    if skill is not None:
        args["skill"] = skill

    sse_cm = sse_client(_LLM_PROXY_URL, timeout=timeout)
    read, write = await sse_cm.__aenter__()
    sess_cm = ClientSession(read, write)
    session = await sess_cm.__aenter__()
    try:
        await session.initialize()
        result = await session.call_tool("ask_auto", args)
        parts = []
        for c in result.content:
            text = getattr(c, "text", None)
            if text is not None:
                parts.append(text)
        raw_text = "\n".join(parts) if parts else ""
        # ask_auto returns JSON: {"text", "model", "tier", "latency_ms", "error"}
        try:
            parsed = json.loads(raw_text)
            return {"raw": parsed.get("text", ""), "model": parsed.get("model", ""), "parsed": parsed}
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat as plain text (backwards compat)
            return {"raw": raw_text, "model": "", "parsed": None}
    finally:
        await sess_cm.__aexit__(None, None, None)
        await sse_cm.__aexit__(None, None, None)


async def _call_llm_async(
    prompt: str,
    tier: str,
    system_prompt: str | None,
    max_tokens: int,
    skill: str | None = None,
) -> dict[str, Any]:
    timeout = _TIMEOUTS.get(tier, 120.0)
    t0 = time.monotonic()

    last_exc: BaseException | None = None
    for attempt in range(2):  # 1 retry on timeout/connection error
        try:
            raw = await _call_ask_auto(prompt, tier, system_prompt, max_tokens, timeout, skill=skill)
            text = raw.get("raw", "")
            model = raw.get("model", "")
            latency_ms = int((time.monotonic() - t0) * 1000)

            if text.startswith("ERROR:"):
                return {
                    "text": "",
                    "model": model,
                    "tier": tier,
                    "latency_ms": latency_ms,
                    "error": text,
                }
            return {
                "text": text,
                "model": model,
                "tier": tier,
                "latency_ms": latency_ms,
                "error": None,
            }
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_retryable(exc):
                # 1 retry
                continue
            break

    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "text": "",
        "model": "",
        "tier": tier,
        "latency_ms": latency_ms,
        "error": f"{type(last_exc).__name__}: {last_exc}",
    }


def call_llm(
    prompt: str,
    tier: str = "medium",
    system_prompt: str | None = None,
    max_tokens: int = 1024,
    skill: str | None = None,
) -> dict[str, Any]:
    """
    Synchronous LLM call through hermes-llm-proxy.

    Thread-safe: works from any context —
      - main thread with a running asyncio loop (research path)
      - background thread without a loop (cron-scheduler / review-learn)
      - plain synchronous code

    Args:
        prompt:        User / task prompt.
        tier:          "easy" | "medium" | "hard"
        system_prompt: Optional system/instruction prefix.
        max_tokens:    Max output tokens.
        skill:         Optional skill name for cost tracking ("research", "review-learn", etc.)

    Returns:
        {text, model, tier, latency_ms, error}
    """
    try:
        asyncio.get_running_loop()
        # We are inside a running loop — run coroutine in a fresh thread with its own loop
        result_container: dict[str, Any] = {}

        def _runner() -> None:
            new_loop = asyncio.new_event_loop()
            try:
                result_container["result"] = new_loop.run_until_complete(
                    _call_llm_async(prompt, tier, system_prompt, max_tokens, skill=skill)
                )
            finally:
                new_loop.close()

        t = threading.Thread(target=_runner)
        t.start()
        t.join()
        return result_container.get("result", {
            "text": "", "model": "", "tier": tier, "latency_ms": 0,
            "error": "call_llm: runner thread produced no result",
        })
    except RuntimeError:
        # No running loop (e.g. cron-scheduler thread, plain sync code) — safe to use asyncio.run()
        return asyncio.run(_call_llm_async(prompt, tier, system_prompt, max_tokens, skill=skill))
