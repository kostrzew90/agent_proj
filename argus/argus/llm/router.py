import os
import re
import time
import threading
import logging
from datetime import datetime, timezone
from collections import deque

import httpx

logger = logging.getLogger(__name__)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
ALLOW_PAID = os.getenv("ARGUS_LLM_ALLOW_PAID", "false").lower() == "true"
PAID_MODEL = os.getenv("ARGUS_LLM_PAID_MODEL", "openai/gpt-4o-mini")
GEMINI_MODEL = os.getenv("ARGUS_GEMINI_MODEL", "gemini-flash-latest")
OR_FREE_MODEL = os.getenv("ARGUS_OR_FREE_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

_PRICING = {"openai/gpt-4o-mini": (0.15, 0.60)}

# Per-provider RPM caps (conservative, below free-tier limits)
# Gemini Flash free: 15 RPM → 10; OpenRouter free: 20 RPM → 8
_RPM_LIMITS = {
    "gemini":     int(os.getenv("ARGUS_GEMINI_RPM", "10")),
    "openrouter": int(os.getenv("ARGUS_OR_RPM", "8")),
}
_MAX_COOLDOWN = 960  # 16 min max backoff after repeated 429s


class _ProviderState:
    """Sliding-window RPM limiter + exponential-backoff circuit breaker."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self._lock = threading.Lock()
        self._window: deque[float] = deque()  # call timestamps within last 60s
        self._blocked_until: float = 0.0
        self._streak: int = 0  # consecutive 429s

    def available(self) -> bool:
        now = time.time()
        with self._lock:
            if self._blocked_until > now:
                return False
            while self._window and now - self._window[0] >= 60:
                self._window.popleft()
            return len(self._window) < self.rpm

    def seconds_until_free(self) -> int:
        with self._lock:
            return max(0, int(self._blocked_until - time.time()))

    def record_success(self):
        with self._lock:
            self._window.append(time.time())
            self._streak = 0

    def record_429(self):
        now = time.time()
        with self._lock:
            self._window.append(now)
            self._streak += 1
            cooldown = min(60 * (2 ** (self._streak - 1)), _MAX_COOLDOWN)
            self._blocked_until = now + cooldown
            logger.warning("provider 429 streak=%d -> cooldown %ds", self._streak, cooldown)

    def record_5xx(self):
        now = time.time()
        with self._lock:
            self._window.append(now)
            # flat 90s cooldown — transient server overload, not quota
            if self._blocked_until < now + 90:
                self._blocked_until = now + 90

    def record_error(self):
        with self._lock:
            self._window.append(time.time())


_STATES: dict[str, _ProviderState] = {
    p: _ProviderState(rpm) for p, rpm in _RPM_LIMITS.items()
}

# ── Alarm ────────────────────────────────────────────────────────────────────
_last_alarm: float = 0.0
_ALARM_SILENCE = 3600  # silence repeat alarms for 1h


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


# ── Internal call helpers ─────────────────────────────────────────────────────

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


def _is_429(exc: Exception) -> bool:
    return "429" in str(exc) or (
        hasattr(exc, "response") and getattr(exc.response, "status_code", 0) == 429
    )


def _sanitize(msg: str) -> str:
    """Remove API keys from error strings before logging."""
    return re.sub(r'key=[A-Za-z0-9_\-]+', 'key=***', msg)


def _is_server_error(exc: Exception) -> bool:
    if hasattr(exc, "response"):
        return 500 <= getattr(exc.response, "status_code", 0) < 600
    s = str(exc)
    return any(code in s for code in ("500", "502", "503", "504"))


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


# ── Public API ────────────────────────────────────────────────────────────────

def call_llm(prompt: str, system: str = "", max_tokens: int = 512) -> str:
    attempts = [
        ("gemini",     GEMINI_MODEL,  lambda: _gemini(prompt, system, max_tokens)),
        ("openrouter", OR_FREE_MODEL, lambda: _openrouter(OR_FREE_MODEL, prompt, system, max_tokens)),
    ]
    if ALLOW_PAID:
        attempts.append(("openrouter", PAID_MODEL, lambda: _openrouter(PAID_MODEL, prompt, system, max_tokens)))

    last_err = None
    all_skipped = True

    for provider, model, fn in attempts:
        state = _STATES.get(provider)
        if state and not state.available():
            logger.debug("skip %s/%s: rate-limited (%ds left)", provider, model, state.seconds_until_free())
            continue

        all_skipped = False
        t0 = time.time()
        try:
            text, usage = fn()
            _record(provider, model, usage, int((time.time() - t0) * 1000), True, None)
            if state:
                state.record_success()
            return text
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            is429 = _is_429(e)
            _record(provider, model, {}, latency, False, str(e))
            if state:
                if is429:
                    state.record_429()
                elif _is_server_error(e):
                    state.record_5xx()
                else:
                    state.record_error()
            last_err = e
            logger.warning("llm %s/%s failed%s: %s", provider, model, " [429]" if is429 else "", _sanitize(str(e)))

    if all_skipped:
        info = "; ".join(
            f"{p}: {_STATES[p].seconds_until_free()}s left"
            for p, _, _ in attempts
            if p in _STATES
        )
        _send_alarm(f"All LLM providers rate-limited — pipeline paused.\n{info}")
        raise RuntimeError(f"all llm providers rate-limited: {info}")

    _send_alarm(f"All LLM providers failed: {last_err}")
    raise RuntimeError(f"all llm providers failed: {last_err}")
