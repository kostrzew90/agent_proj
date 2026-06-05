import os
import time
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
ALLOW_PAID = os.getenv("ARGUS_LLM_ALLOW_PAID", "false").lower() == "true"
PAID_MODEL = os.getenv("ARGUS_LLM_PAID_MODEL", "openai/gpt-4o-mini")
GEMINI_MODEL = "gemini-2.0-flash"
OR_FREE_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# USD per 1M tokens (in, out); free / unknown -> 0
_PRICING = {"openai/gpt-4o-mini": (0.15, 0.60)}

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

def _gemini(prompt: str, system: str, max_tokens: int):
    if not GEMINI_KEY:
        raise RuntimeError("no gemini key")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    text = f"{system}\n\n{prompt}" if system else prompt
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0}}
    r = httpx.post(url, json=body, timeout=60)
    r.raise_for_status()
    j = r.json()
    out = j["candidates"][0]["content"]["parts"][0]["text"]
    um = j.get("usageMetadata", {})
    usage = {"tokens_in": um.get("promptTokenCount", 0), "tokens_out": um.get("candidatesTokenCount", 0)}
    return out, usage

def _openrouter(model: str, prompt: str, system: str, max_tokens: int):
    if not OPENROUTER_KEY:
        raise RuntimeError("no openrouter key")
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                   headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
                   json={"model": model,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": prompt}],
                         "max_tokens": max_tokens, "temperature": 0},
                   timeout=60)
    r.raise_for_status()
    j = r.json()
    out = j["choices"][0]["message"]["content"]
    u = j.get("usage", {})
    usage = {"tokens_in": u.get("prompt_tokens", 0), "tokens_out": u.get("completion_tokens", 0)}
    return out, usage

def call_llm(prompt: str, system: str = "", max_tokens: int = 512) -> str:
    attempts = [
        ("gemini", GEMINI_MODEL, lambda: _gemini(prompt, system, max_tokens)),
        ("openrouter", OR_FREE_MODEL, lambda: _openrouter(OR_FREE_MODEL, prompt, system, max_tokens)),
    ]
    if ALLOW_PAID:
        attempts.append(("openrouter", PAID_MODEL, lambda: _openrouter(PAID_MODEL, prompt, system, max_tokens)))
    last_err = None
    for provider, model, fn in attempts:
        t0 = time.time()
        try:
            text, usage = fn()
            _record(provider, model, usage, int((time.time() - t0) * 1000), True, None)
            return text
        except Exception as e:
            _record(provider, model, {}, int((time.time() - t0) * 1000), False, str(e))
            last_err = e
            logger.warning("llm %s/%s failed: %s", provider, model, e)
    raise RuntimeError(f"all llm providers failed: {last_err}")
