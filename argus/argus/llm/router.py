import os
import re
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

_PRICING = {"openai/gpt-4o-mini": (0.15, 0.60)}

# ── Alarm ────────────────────────────────────────────────────────────────────
_last_alarm: float = 0.0
_ALARM_SILENCE = 1800  # silence repeat alarms for 30 min (batch calls LLM up to 8x in a row)


def _send_alarm(msg: str):
    global _last_alarm
    now = time.time()
    if now - _last_alarm < _ALARM_SILENCE:
        return
    _last_alarm = now
    logger.critical("ALARM: %s", msg)
    if TG_TOKEN and TG_CHAT:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT, "text": f"🚨 Argus LLM alarm\n{msg}"},
                timeout=10,
            )
        except Exception as e:
            logger.warning("telegram alarm failed: %s", e)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cost(model: str, usage: dict) -> float:
    pin, pout = _PRICING.get(model, (0.0, 0.0))
    return round(usage.get("tokens_in", 0) / 1e6 * pin + usage.get("tokens_out", 0) / 1e6 * pout, 6)


def _record(provider: str, model: str, usage: dict, latency_ms: int, ok: bool, error):
    try:
        from argus.db import SessionLocal
        from argus.models import LlmCall
        with SessionLocal() as s:
            s.add(LlmCall(ts=datetime.now(timezone.utc), provider=provider, model=model,
                          tokens_in=usage.get("tokens_in", 0), tokens_out=usage.get("tokens_out", 0),
                          cost_usd=_cost(model, usage), latency_ms=latency_ms, ok=ok,
                          error=(error[:300] if error else None)))
            s.commit()
    except Exception as e:
        logger.warning("llm_call record failed: %s", e)

    try:
        from argus.llmops_client import record as _llmops_record
        _llmops_record(provider=provider, model=model, call_type="generate",
                       tokens_in=usage.get("tokens_in", 0),
                       tokens_out=usage.get("tokens_out", 0),
                       latency_ms=latency_ms, ok=ok,
                       error=(str(error) if error else None))
    except Exception:
        pass


def _sanitize(msg: str) -> str:
    """Remove API keys from error strings before logging."""
    msg = re.sub(r'key=[A-Za-z0-9_\-]+', 'key=***', msg)
    secret = os.getenv("LITELLM_API_KEY", "")
    if secret:
        msg = msg.replace(secret, "***")
    return msg


def _actual_model(resp: httpx.Response, body: dict, requested: str) -> str:
    """Model that actually answered, from documented LiteLLM response headers.

    x-litellm-model-group = routed model_name; x-litellm-model-api-base = upstream
    base URL (tells Mac/Gemini/OpenRouter apart when the group has many deployments).
    https://docs.litellm.ai/docs/proxy/response_headers
    """
    group = resp.headers.get("x-litellm-model-group") or body.get("model") or requested
    base = resp.headers.get("x-litellm-model-api-base", "")
    host = urlparse(base).netloc if base else ""
    return f"{group}@{host}" if host else group


def _fail(model: str, t0: float, err: str):
    err = _sanitize(err)
    _record("litellm", model, {}, int((time.time() - t0) * 1000), False, err)
    _send_alarm(f"LLM (LiteLLM) call failed: {err[:300]}")
    raise RuntimeError(err)


def call_llm(prompt: str, system: str = "", max_tokens: int = 512) -> str:
    """One request to the LiteLLM gateway (which handles provider fallback/cooldowns).

    Exceptions propagate — the caller must NOT cache the result on failure.
    """
    url = os.getenv("LITELLM_URL", "").rstrip("/")
    key = os.getenv("LITELLM_API_KEY", "")
    model = os.getenv("ARGUS_LLM_MODEL", "argus-extract")
    timeout = float(os.getenv("ARGUS_LLM_TIMEOUT", "300"))
    t0 = time.time()

    if not url or not key:
        _fail(model, t0, "LiteLLM not configured: LITELLM_URL and LITELLM_API_KEY are required")

    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    try:
        r = httpx.post(f"{url}/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "messages": messages, "max_tokens": max_tokens,
                             "temperature": 0},
                       timeout=timeout)
    except Exception as e:
        _fail(model, t0, f"LiteLLM request failed: {type(e).__name__}: {e}")

    if r.status_code != 200:
        _fail(model, t0, f"LiteLLM HTTP {r.status_code}: {r.text[:200]}")

    try:
        j = r.json()
        out = j["choices"][0]["message"]["content"]
        if not out:
            raise ValueError("empty content")
    except Exception as e:
        _fail(model, t0, f"LiteLLM bad response: {type(e).__name__}: {e}")

    u = j.get("usage") or {}
    usage = {"tokens_in": u.get("prompt_tokens", 0), "tokens_out": u.get("completion_tokens", 0)}
    fallbacks = r.headers.get("x-litellm-attempted-fallbacks")
    if fallbacks and fallbacks != "0":
        logger.warning("LiteLLM fallback used (attempted_fallbacks=%s, retries=%s, api_base=%s)",
                       fallbacks, r.headers.get("x-litellm-attempted-retries", "0"),
                       r.headers.get("x-litellm-model-api-base", "?"))
    _record("litellm", _actual_model(r, j, model), usage, int((time.time() - t0) * 1000), True, None)
    return out
