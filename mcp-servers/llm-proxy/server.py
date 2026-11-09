import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Optional

from google import genai
import requests
from mcp.server.fastmcp import FastMCP

try:
    import psycopg2
    import psycopg2.extras
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

mcp = FastMCP("llm-proxy", host="0.0.0.0")


# ---------------------------------------------------------------------------
# Audit / cost paths
# ---------------------------------------------------------------------------

_AUDIT_DIR = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit"))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

COST_LOG = _AUDIT_DIR / "costs.jsonl"
AUDIT_LOG = _AUDIT_DIR / "llm-proxy.jsonl"

# Cost table: (input_per_1m_usd, output_per_1m_usd)
_COST_TABLE: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.0, 0.0),
    "ollama": (0.0, 0.0),
}
_FREE_SUFFIX = ":free"


# ---------------------------------------------------------------------------
# Cost tracking helpers
# ---------------------------------------------------------------------------

def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    if model in _COST_TABLE:
        rate_in, rate_out = _COST_TABLE[model]
        return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000
    if model.endswith(_FREE_SUFFIX):
        return 0.0
    # Paid OpenRouter fallback placeholder: $3/$15 per 1M
    return (tokens_in * 3.0 + tokens_out * 15.0) / 1_000_000


def _record_cost(
    tool: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    caller: str | None = None,
    skill: str | None = None,
    tier: str | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    provider: str | None = None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "caller": caller,
        "skill": skill,
        "tier": tier,
        "latency_ms": latency_ms,
        "error": error,
    }
    try:
        with COST_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    # Also write to Postgres if PG_DSN is configured
    _insert_pg(
        caller=tool,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        error=error,
        skill=skill,
        tier=tier,
    )

    try:
        from llmops_client import record as _llmops_record
        _llmops_record(
            provider=provider if provider is not None else tool.replace("ask_", ""),
            model=model,
            call_type="generate",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_estimated=True,
            latency_ms=latency_ms,
            ok=error is None,
            error=error,
        )
    except Exception:
        pass


def _week_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _weekly_spent() -> float:
    week_start = _week_start_utc()
    total = 0.0
    if not COST_LOG.exists():
        return total
    try:
        with COST_LOG.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["ts"])
                    if ts >= week_start:
                        total += float(entry.get("cost_usd", 0.0))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except Exception:
        pass
    return total


def _budget_remaining() -> float:
    cap = float(os.environ.get("WEEKLY_BUDGET_USD", "10"))
    return cap - _weekly_spent()


# ---------------------------------------------------------------------------
# Postgres writer (optional — requires PG_DSN env var)
# ---------------------------------------------------------------------------

_pg_conn = None  # lazy global connection; reset on error


def _get_pg_conn():
    """Return a live psycopg2 connection or None if unavailable."""
    global _pg_conn
    if not _PSYCOPG2_AVAILABLE:
        return None
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        return None
    if _pg_conn is not None:
        try:
            # cheap liveness check
            _pg_conn.cursor().execute("SELECT 1")
            return _pg_conn
        except Exception:
            try:
                _pg_conn.close()
            except Exception:
                pass
            _pg_conn = None
    try:
        _pg_conn = psycopg2.connect(dsn)
        _pg_conn.autocommit = True
        return _pg_conn
    except Exception as e:
        print(f"[llm-proxy] PG connect failed: {e}", flush=True)
        _pg_conn = None
        return None


def _insert_pg(
    caller: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_ms: int | None = None,
    error: str | None = None,
    skill: str | None = None,
    tier: str | None = None,
) -> None:
    """Insert a cost record into hermes_llm_costs. Silently skips if PG unavailable."""
    global _pg_conn
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hermes_llm_costs
                    (caller, skill, tier, model, tokens_in, tokens_out,
                     cost_usd, latency_ms, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (caller, skill, tier, model, tokens_in, tokens_out,
                 cost_usd, latency_ms, error),
            )
    except Exception as e:
        print(f"[llm-proxy] PG insert failed: {e}", flush=True)
        # reset connection so next call tries fresh
        try:
            conn.close()
        except Exception:
            pass
        _pg_conn = None


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------

def _audit(
    tool: str,
    model: str,
    prompt_len: int,
    response_len: int,
    latency_ms: float,
    error: str | None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "model": model,
        "prompt_len": prompt_len,
        "response_len": response_len,
        "latency_ms": round(latency_ms, 1),
        "error": error,
    }
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, model: str, system_prompt: Optional[str], max_tokens: int) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "ERROR: GEMINI_API_KEY not set"
    try:
        client = genai.Client(api_key=api_key)
        config = genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response.text
    except Exception as e:
        return f"ERROR: {e}"


def _call_openrouter(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "ERROR: OPENROUTER_API_KEY not set"
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


def _call_ollama(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    location: Literal["laptop", "mac"] = "laptop",
) -> str:
    if location == "mac":
        base_url = os.environ.get("OLLAMA_MAC_URL", "http://100.73.220.16:11434")
    else:
        base_url = os.environ.get("OLLAMA_LAPTOP_URL", "http://host.docker.internal:11434")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def ask_gemini(
    prompt: str,
    model: str = "gemini-2.0-flash",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    skill: Optional[str] = None,
) -> str:
    """Ask Gemini. Free via Google AI Studio/Google One. Good for research, analysis, text."""
    t0 = time.monotonic()
    result = _call_gemini(prompt, model, system_prompt, max_tokens)
    latency = (time.monotonic() - t0) * 1000
    latency_ms = int(latency)
    err = result if result.startswith("ERROR:") else None
    _audit("ask_gemini", model, len(prompt), len(result), latency, err)
    tokens_in = len(prompt) // 4
    tokens_out = len(result) // 4
    _record_cost(
        "ask_gemini", model, tokens_in, tokens_out,
        _estimate_cost(model, tokens_in, tokens_out),
        skill=skill, latency_ms=latency_ms, error=err,
    )
    return result


@mcp.tool()
def ask_openrouter(
    prompt: str,
    model: str = "meta-llama/llama-4-maverick:free",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    skill: Optional[str] = None,
) -> str:
    """Ask via OpenRouter free models to save Claude rate limits.
    Free models: meta-llama/llama-4-maverick:free, qwen/qwen3-235b-a22b:free, google/gemma-3-27b-it:free"""
    t0 = time.monotonic()
    result = _call_openrouter(prompt, model, system_prompt, max_tokens)
    latency = (time.monotonic() - t0) * 1000
    latency_ms = int(latency)
    err = result if result.startswith("ERROR:") else None
    _audit("ask_openrouter", model, len(prompt), len(result), latency, err)
    tokens_in = len(prompt) // 4
    tokens_out = len(result) // 4
    _record_cost(
        "ask_openrouter", model, tokens_in, tokens_out,
        _estimate_cost(model, tokens_in, tokens_out),
        skill=skill, latency_ms=latency_ms, error=err,
    )
    return result


@mcp.tool()
def ask_ollama(
    prompt: str,
    model: str = "qwen2.5-coder:3b",
    system_prompt: Optional[str] = None,
    location: Literal["laptop", "mac"] = "laptop",
    skill: Optional[str] = None,
) -> str:
    """Ask a local Ollama instance. location='laptop' uses host.docker.internal:11434,
    location='mac' uses Mac Studio (OLLAMA_MAC_URL). Free, no quota."""
    t0 = time.monotonic()
    result = _call_ollama(prompt, model, system_prompt, location)
    latency = (time.monotonic() - t0) * 1000
    latency_ms = int(latency)
    err = result if result.startswith("ERROR:") else None
    _audit("ask_ollama", model, len(prompt), len(result), latency, err)
    tokens_in = len(prompt) // 4
    tokens_out = len(result) // 4
    _record_cost(
        "ask_ollama", model, tokens_in, tokens_out,
        _estimate_cost(model, tokens_in, tokens_out),
        skill=skill, latency_ms=latency_ms, error=err,
    )
    return result


@mcp.tool()
def ask_auto(
    prompt: str,
    complexity: Literal["easy", "medium", "hard"] = "easy",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    skill: Optional[str] = None,
) -> str:
    """Smart LLM router.
    easy:   OpenRouter llama-4-maverick:free → laptop gemma4:e4b.
    medium: Gemini 2.0-flash → Mac gemma4:31b.
    hard:   Mac qwen3.6:35b → Mac gemma4:31b → Gemini → OpenRouter.
    Checks weekly budget before paid calls.
    Returns JSON: {"text": str, "model": str, "tier": str, "latency_ms": int, "error": str|null}"""
    cap = float(os.environ.get("WEEKLY_BUDGET_USD", "10"))
    remaining = _budget_remaining()
    if remaining <= 0:
        err_msg = f"ERROR: weekly LLM budget (${cap}) exhausted — resets Monday 00:00 UTC"
        return json.dumps({"text": "", "model": "", "tier": complexity, "latency_ms": 0, "error": err_msg})

    t0 = time.monotonic()
    model_used = ""
    provider_used = ""
    result = ""

    if complexity == "easy":
        model_used = "meta-llama/llama-4-maverick:free"
        provider_used = "openrouter"
        result = _call_openrouter(prompt, model_used, system_prompt, max_tokens)
        if result.startswith("ERROR:"):
            model_used = "gemma4:e4b"
            provider_used = "ollama"
            result = _call_ollama(prompt, model_used, system_prompt, location="laptop")

    elif complexity == "medium":
        model_used = "gemini-2.0-flash"
        provider_used = "gemini"
        result = _call_gemini(prompt, model_used, system_prompt, max_tokens)
        if result.startswith("ERROR:"):
            model_used = "gemma4:31b"
            provider_used = "ollama"
            result = _call_ollama(prompt, model_used, system_prompt, location="mac")

    else:  # hard
        model_used = "qwen3.6:35b"
        provider_used = "ollama"
        result = _call_ollama(prompt, model_used, system_prompt, location="mac")
        if result.startswith("ERROR:"):
            model_used = "gemma4:31b"
            provider_used = "ollama"
            result = _call_ollama(prompt, model_used, system_prompt, location="mac")
        if result.startswith("ERROR:"):
            model_used = "gemini-2.0-flash"
            provider_used = "gemini"
            result = _call_gemini(prompt, model_used, system_prompt, max_tokens)
        if result.startswith("ERROR:"):
            model_used = "meta-llama/llama-4-maverick:free"
            provider_used = "openrouter"
            result = _call_openrouter(prompt, model_used, system_prompt, max_tokens)

    latency = (time.monotonic() - t0) * 1000
    latency_ms = int(latency)
    err = result if result.startswith("ERROR:") else None
    _audit("ask_auto", model_used, len(prompt), len(result), latency, err)
    tokens_in = len(prompt) // 4
    tokens_out = len(result) // 4
    _record_cost(
        "ask_auto", model_used, tokens_in, tokens_out,
        _estimate_cost(model_used, tokens_in, tokens_out),
        skill=skill, tier=complexity, latency_ms=latency_ms, error=err,
        provider=provider_used,
    )
    return json.dumps({
        "text": result if not err else "",
        "model": model_used,
        "tier": complexity,
        "latency_ms": latency_ms,
        "error": err,
    })


@mcp.tool()
def budget_status() -> dict:
    """Return weekly LLM budget status: cap, spent, remaining, call count, week start."""
    cap = float(os.environ.get("WEEKLY_BUDGET_USD", "10"))
    week_start = _week_start_utc()
    spent = 0.0
    calls = 0
    if COST_LOG.exists():
        try:
            with COST_LOG.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["ts"])
                        if ts >= week_start:
                            spent += float(entry.get("cost_usd", 0.0))
                            calls += 1
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception:
            pass
    return {
        "weekly_cap_usd": cap,
        "spent_this_week_usd": round(spent, 6),
        "remaining_usd": round(cap - spent, 6),
        "calls_this_week": calls,
        "week_start_utc": week_start.isoformat(),
    }


if __name__ == "__main__":
    import os as _os
    _transport = _os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if _transport == "sse":
        mcp.settings.host = _os.environ.get("MCP_HOST", "0.0.0.0")
        mcp.settings.port = int(_os.environ.get("MCP_PORT", "8000"))
        mcp.run(transport="sse")
    else:
        mcp.run()
