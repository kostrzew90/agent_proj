# Argus Increment 6 — LLM topic→ticker (gap-fill) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dla itemów, których `rule-v2` nie złapał, wyciągnąć semantyczne claimy topic→ticker przez LLM (free-first router + cache), inline w `collect_rss`, jako `method="llm"` z confidence 0.35.

**Architecture:** Cienki `llm/router.py` (Gemini free → OpenRouter free → opcj. paid gated env) + `llm/extractor.py` (wąski prompt + grounding gate, walidacja watchlisty, stałe confidence) + `llm/cache.py` (`llm_cache` po text_hash, też puste wyniki). `collect_rss` wywołuje gap-fill inline gdy reguły dały 0. Bez nowego joba/kontenera. httpx (bez nowej zależności).

**Tech Stack:** Python 3.12, httpx, SQLAlchemy, pytest. Testy w Dockerze.

**Spec:** `docs/superpowers/specs/2026-06-05-argus-llm-topic-ticker-design.md`

**⚠️ Prerequisite (Task 9):** `GEMINI_API_KEY` + `OPENROUTER_API_KEY` muszą być w `~/argus/.env` na VPS (sekrety — user wstawia; .env gitignored). Bez nich LLM = no-op (gap zostaje pusty, system działa dalej).

**Monitoring (wymóg usera):** każde wywołanie LLM (Gemini/OpenRouter, też darmowe) rejestrowane w tabeli `llm_calls` (provider, model, tokeny, koszt USD wg cennika [free=0], latencja, ok/fail) → endpoint `/api/llm/usage` + panel (Tasks 7-8). Kontrola kosztów = cache + `ARGUS_LLM_ALLOW_PAID` (default off) + `ARGUS_LLM_MAX_PER_RUN` cap (bez osobnego metering USD poza `llm_calls`).

---

## Konwencje
- **Brak lokalnego pythona.** Testy w Dockerze (PowerShell; trusted-host przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- `call_llm(prompt, system="", max_tokens=512) -> str`. `extract_claims_llm(text, assets, sector_map=None) -> list[LlmClaim]`. `LlmClaim(asset_symbol, direction, confidence, reasoning)`. `LLM_DEFAULT_CONFIDENCE=0.35`, `PROMPT_VERSION="llm-v1"`.
- Cache: `text_hash(text)`, `cache_get(session,h)->list|None` (None=miss), `cache_put(session,h,result:list)`.

## Struktura plików
```
argus/argus/models.py            # MOD — Task 1 (LlmCache + LlmCall)
argus/argus/llm/__init__.py      # NOWY — Task 2 (pusty)
argus/argus/llm/router.py        # NOWY — Task 2 (router + recording + pricing)
argus/argus/llm/extractor.py     # NOWY — Task 3
argus/argus/llm/cache.py         # NOWY — Task 4
argus/argus/collectors/rss.py    # MOD — Task 5 (gap-fill inline)
argus/.env.example               # MOD — Task 6
argus/argus/api.py               # MOD — Task 7 (/api/llm/usage)
argus/argus/web/index.html,app.js# MOD — Task 8 (panel LLM usage)
argus/tests/test_models.py       # MOD — Task 1
argus/tests/test_llm_router.py   # NOWY — Task 2
argus/tests/test_llm_extractor.py# NOWY — Task 3
argus/tests/test_llm_cache.py    # NOWY — Task 4
argus/tests/test_rss.py          # MOD — Task 5
argus/tests/test_api.py          # MOD — Task 7
```

---

### Task 1: `LlmCache` + `LlmCall` models

**Files:** Modify `argus/argus/models.py`; Modify `argus/tests/test_models.py`

- [ ] **Step 1: Append failing test to `argus/tests/test_models.py`**
```python
def test_llm_cache_roundtrip(session):
    from datetime import datetime, timezone
    from argus.models import LlmCache
    session.add(LlmCache(text_hash="abc123", result_json=[{"asset": "BTC", "direction": "bull", "reasoning": "x"}],
                         created_at=datetime.now(timezone.utc)))
    session.commit()
    row = session.get(LlmCache, "abc123")
    assert row.result_json[0]["asset"] == "BTC"
    # empty result is storable too
    session.add(LlmCache(text_hash="empty1", result_json=[], created_at=datetime.now(timezone.utc)))
    session.commit()
    assert session.get(LlmCache, "empty1").result_json == []

def test_llm_call_roundtrip(session):
    from datetime import datetime, timezone
    from argus.models import LlmCall
    session.add(LlmCall(ts=datetime.now(timezone.utc), provider="gemini", model="gemini-2.0-flash",
                        tokens_in=120, tokens_out=40, cost_usd=0.0, latency_ms=850, ok=True, error=None))
    session.commit()
    row = session.query(LlmCall).one()
    assert row.provider == "gemini" and row.ok is True and row.cost_usd == 0.0
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_models.py -k "llm_cache or llm_call"` → ImportError.

- [ ] **Step 3: Append to `argus/argus/models.py`** (`JSON` already imported):
```python
class LlmCache(Base):
    __tablename__ = "llm_cache"
    text_hash: Mapped[str] = mapped_column(String, primary_key=True)
    result_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String)            # gemini|openrouter
    model: Mapped[str] = mapped_column(String)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_models.py` → all green.

- [ ] **Step 5: Commit**
```
git add argus/argus/models.py argus/tests/test_models.py
git commit -m "feat(argus): LlmCache + LlmCall models (extraction cache + call monitoring)"
```

---

### Task 2: `llm/router.py` (free→paid gated + per-call recording)

**Files:** Create `argus/argus/llm/__init__.py` (empty), `argus/argus/llm/router.py`; Test `argus/tests/test_llm_router.py`

Providers return `(text, usage)` where `usage={"tokens_in":int,"tokens_out":int}`. Every attempt (incl. free + failures) is recorded via `_record(...)` → `llm_calls` (best-effort, own SessionLocal). `_record` is module-level so tests can monkeypatch it.

- [ ] **Step 1: Write failing test `argus/tests/test_llm_router.py`**
```python
from unittest.mock import patch
import argus.llm.router as router

def test_cost_free_zero_paid_nonzero():
    assert router._cost("meta-llama/llama-3.3-70b-instruct:free", {"tokens_in": 1000, "tokens_out": 1000}) == 0.0
    assert router._cost("openai/gpt-4o-mini", {"tokens_in": 1_000_000, "tokens_out": 0}) > 0

def test_falls_back_to_openrouter_when_gemini_fails(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)
    with patch.object(router, "_gemini", side_effect=RuntimeError("down")), \
         patch.object(router, "_openrouter", return_value=("OK-OR", {"tokens_in": 5, "tokens_out": 7})) as orm:
        assert router.call_llm("p") == "OK-OR"
        assert orm.called

def test_paid_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    monkeypatch.setattr(router, "ALLOW_PAID", False)
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)
    with patch.object(router, "_gemini", side_effect=RuntimeError("x")), \
         patch.object(router, "_openrouter", side_effect=RuntimeError("y")):
        try:
            router.call_llm("p"); assert False
        except RuntimeError:
            pass

def test_paid_used_when_enabled(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    monkeypatch.setattr(router, "ALLOW_PAID", True)
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)
    def fake_or(model, *a, **k):
        if ":free" in model:
            raise RuntimeError("free down")
        return ("PAID-OK", {"tokens_in": 1, "tokens_out": 1})
    with patch.object(router, "_gemini", side_effect=RuntimeError("g")), \
         patch.object(router, "_openrouter", side_effect=fake_or):
        assert router.call_llm("p") == "PAID-OK"

def test_records_each_attempt(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    rec = []
    monkeypatch.setattr(router, "_record", lambda provider, model, usage, latency_ms, ok, error: rec.append((provider, ok)))
    with patch.object(router, "_gemini", side_effect=RuntimeError("g")), \
         patch.object(router, "_openrouter", return_value=("hi", {"tokens_in": 2, "tokens_out": 2})):
        router.call_llm("p")
    assert ("gemini", False) in rec and ("openrouter", True) in rec   # failed + success both recorded
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/llm/__init__.py`** (empty) and `argus/argus/llm/router.py`:
```python
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
    """Best-effort write to llm_calls (own session; never raises into caller)."""
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
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_llm_router.py` → `5 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/llm/__init__.py argus/argus/llm/router.py argus/tests/test_llm_router.py
git commit -m "feat(argus): llm router (free->paid) + per-call recording to llm_calls"
```

---

### Task 3: `llm/extractor.py`

**Files:** Create `argus/argus/llm/extractor.py`; Test `argus/tests/test_llm_extractor.py`

- [ ] **Step 1: Write failing test `argus/tests/test_llm_extractor.py`**
```python
from unittest.mock import patch
from argus.models import Asset
import argus.llm.extractor as ex

ASSETS = [Asset(symbol="BTC", kind="crypto"), Asset(symbol="NFE", kind="stock")]

def test_valid_json_yields_fixed_confidence():
    raw = '[{"asset":"BTC","direction":"bull","reasoning":"Fed dovish -> risk on"}]'
    with patch.object(ex, "call_llm", return_value=raw):
        out = ex.extract_claims_llm("Fed signals cuts", ASSETS)
    assert len(out) == 1
    assert out[0].asset_symbol == "BTC" and out[0].direction == "bull"
    assert out[0].confidence == ex.LLM_DEFAULT_CONFIDENCE == 0.35
    assert "Fed" in out[0].reasoning

def test_hallucinated_ticker_rejected():
    raw = '[{"asset":"DOGE","direction":"bull","reasoning":"x"}]'
    with patch.object(ex, "call_llm", return_value=raw):
        assert ex.extract_claims_llm("doge to moon", ASSETS) == []

def test_markdown_fenced_json_parsed():
    raw = '```json\n[{"asset":"NFE","direction":"bear","reasoning":"gas glut"}]\n```'
    with patch.object(ex, "call_llm", return_value=raw):
        out = ex.extract_claims_llm("natural gas glut", ASSETS)
    assert out[0].asset_symbol == "NFE" and out[0].direction == "bear"

def test_bad_json_returns_empty():
    with patch.object(ex, "call_llm", return_value="sorry, no idea"):
        assert ex.extract_claims_llm("noise", ASSETS) == []

def test_llm_error_returns_empty():
    with patch.object(ex, "call_llm", side_effect=RuntimeError("down")):
        assert ex.extract_claims_llm("x", ASSETS) == []
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/llm/extractor.py`**
```python
import json
import logging
from dataclasses import dataclass

from argus.llm.router import call_llm

logger = logging.getLogger(__name__)
LLM_DEFAULT_CONFIDENCE = 0.35
PROMPT_VERSION = "llm-v1"
_SYSTEM = "Jesteś ekspertem od krypto i makro. Odpowiadasz WYŁĄCZNIE poprawnym JSON-em."

@dataclass
class LlmClaim:
    asset_symbol: str
    direction: str
    confidence: float
    reasoning: str

def build_prompt(text: str, assets, sector_map: dict | None) -> str:
    allowed = ", ".join(sorted(a.symbol for a in assets))
    sectors = "\n".join(f"- {', '.join(s.get('aliases', [])[:4])} -> {', '.join(s.get('tickers', []))}"
                        for s in (sector_map or {}).values())
    return (f"Dozwolone assety: {allowed}\n"
            f"Mapowania sektorowe:\n{sectors}\n\n"
            "Z poniższego tekstu wyciągnij TYLKO powiązania kierunkowe z dozwolonych assetów.\n"
            "Zwróć claim WYŁĄCZNIE gdy w tekście jest bezpośrednie lub bardzo silne uzasadnienie. "
            "Jeśli powiązanie jest słabe, spekulacyjne lub wymaga dużej interpretacji — zwróć pustą listę [].\n"
            'Zwróć WYŁĄCZNIE JSON: [{"asset":"SYM","direction":"bull|bear|neutral","reasoning":"krótko"}]\n\n'
            f"Tekst:\n{text}")

def _extract_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return json.loads(raw[start:end + 1])

def extract_claims_llm(text: str, assets, sector_map: dict | None = None) -> list[LlmClaim]:
    known = {a.symbol for a in assets}
    try:
        raw = call_llm(build_prompt(text, assets, sector_map), system=_SYSTEM, max_tokens=400)
        data = _extract_json(raw)
    except Exception as e:
        logger.warning("llm extract failed: %s", e)
        return []
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        sym = (d.get("asset") or "").upper()
        direction = d.get("direction")
        if sym in known and direction in ("bull", "bear", "neutral"):
            out.append(LlmClaim(sym, direction, LLM_DEFAULT_CONFIDENCE, (d.get("reasoning") or "")[:500]))
    return out
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_llm_extractor.py` → `5 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/llm/extractor.py argus/tests/test_llm_extractor.py
git commit -m "feat(argus): llm extractor (constrained prompt + grounding gate, fixed conf)"
```

---

### Task 4: `llm/cache.py`

**Files:** Create `argus/argus/llm/cache.py`; Test `argus/tests/test_llm_cache.py`

- [ ] **Step 1: Write failing test `argus/tests/test_llm_cache.py`**
```python
from argus.llm.cache import text_hash, cache_get, cache_put

def test_hash_stable():
    assert text_hash("abc") == text_hash("abc")
    assert text_hash("abc") != text_hash("abd")

def test_miss_then_hit(session):
    h = text_hash("some headline")
    assert cache_get(session, h) is None                 # miss
    cache_put(session, h, [{"asset": "BTC", "direction": "bull", "reasoning": "r"}])
    assert cache_get(session, h)[0]["asset"] == "BTC"    # hit

def test_empty_result_cached_as_list_not_none(session):
    h = text_hash("boring headline")
    cache_put(session, h, [])
    assert cache_get(session, h) == []                   # empty hit != miss(None)
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/llm/cache.py`**
```python
import hashlib
from datetime import datetime, timezone
from argus.models import LlmCache

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def cache_get(session, h: str):
    row = session.get(LlmCache, h)
    return row.result_json if row is not None else None

def cache_put(session, h: str, result: list) -> None:
    if session.get(LlmCache, h) is None:
        session.add(LlmCache(text_hash=h, result_json=result, created_at=datetime.now(timezone.utc)))
        session.commit()
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_llm_cache.py` → `3 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/llm/cache.py argus/tests/test_llm_cache.py
git commit -m "feat(argus): llm_cache helpers (text_hash dedup, empty cached)"
```

---

### Task 5: `collect_rss` gap-fill inline

**Files:** Modify `argus/argus/collectors/rss.py`; Modify `argus/tests/test_rss.py`

- [ ] **Step 1: Append failing tests to `argus/tests/test_rss.py`**
```python
def test_gap_fill_calls_llm_when_rule_empty(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source, Claim
    from argus.llm.extractor import LlmClaim
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="news", handle="http://f", display_name="WSJ Markets"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g1", title="Fed signals dovish pivot", summary="",
                            link="http://x/g1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm",
               return_value=[LlmClaim("BTC", "bull", 0.35, "dovish -> risk on")]) as mllm:
        collect_rss(session, src)
    assert mllm.called
    c = session.query(Claim).filter_by(asset="BTC").one()
    assert c.method == "llm" and c.confidence == 0.35

def test_no_gap_fill_when_rule_found_claim(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://f2", display_name="r/x"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g2", title="long BTC", summary="", link="http://x/g2",
                            published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm") as mllm:
        collect_rss(session, src)
    assert not mllm.called          # rule-v2 matched "long" -> no LLM

def test_gap_fill_uses_cache_on_second_run(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source, Item
    from argus.llm.extractor import LlmClaim
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s1 = Source(kind="news", handle="http://fa", display_name="WSJ"); session.add(s1)
    s2 = Source(kind="news", handle="http://fb", display_name="MW"); session.add(s2); session.commit()
    def feed_for(_handle):
        e = SimpleNamespace(id=None, title="Fed dovish pivot ahead", summary="",
                            link="http://x/same", published_parsed=(2026,6,5,0,0,0,0,0,0))
        return SimpleNamespace(entries=[e])
    with patch("argus.collectors.rss.feedparser.parse", side_effect=lambda h: feed_for(h)), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm",
               return_value=[LlmClaim("BTC","bull",0.35,"r")]) as mllm:
        collect_rss(session, s1)     # external_id falls back to link "http://x/same"
        collect_rss(session, s2)     # same text -> cache hit -> no 2nd LLM call
    assert mllm.call_count == 1
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_rss.py -k gap` → fails (no gap-fill).

- [ ] **Step 3: Rewrite `argus/argus/collectors/rss.py`**
```python
import os
import calendar
import logging
from datetime import datetime, timezone
from dataclasses import asdict
import yaml
import feedparser
from sqlalchemy import select
from argus.models import Asset, Item, Claim, ClaimAudit
from argus.extract import extract_claims, PARSER_VERSION
from argus.prices import get_spot_price
from argus.llm.extractor import extract_claims_llm, LLM_DEFAULT_CONFIDENCE
from argus.llm.cache import text_hash, cache_get, cache_put

logger = logging.getLogger(__name__)
_LLM_MAX_PER_RUN = int(os.getenv("ARGUS_LLM_MAX_PER_RUN", "30"))

def load_sector_map(path: str = "config/sectors.yaml") -> dict:
    if os.path.exists(path):
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {}

def _published(entry):
    pp = getattr(entry, "published_parsed", None)
    if not pp:
        return None
    return datetime.fromtimestamp(calendar.timegm(pp), tz=timezone.utc)

def _add_claim(session, source, item, asset_symbol, direction, confidence, method,
               parser_version, parsed_claim, raw_text, entry_price, now):
    claim = Claim(source_id=source.id, item_id=item.id, asset=asset_symbol,
                  direction=direction, confidence=confidence, method=method,
                  entry_price=entry_price, entry_ts=now, status="open")
    session.add(claim); session.flush()
    session.add(ClaimAudit(claim_id=claim.id, raw_text=raw_text,
                           parsed_claim=parsed_claim, parser_version=parser_version))

def _gap_fill(session, text, assets, sector_map):
    """Return list of (asset_symbol, direction, reasoning) from cache or LLM."""
    h = text_hash(text)
    cached = cache_get(session, h)
    if cached is not None:
        return [(c["asset"], c["direction"], c.get("reasoning", "")) for c in cached], False
    llm_claims = extract_claims_llm(text, assets, sector_map)
    cache_put(session, h, [{"asset": c.asset_symbol, "direction": c.direction,
                            "reasoning": c.reasoning} for c in llm_claims])
    return [(c.asset_symbol, c.direction, c.reasoning) for c in llm_claims], True

def collect_rss(session, source) -> int:
    feed = feedparser.parse(source.handle)
    assets = list(session.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
    by_symbol = {a.symbol: a for a in assets}
    sector_map = load_sector_map()
    now = datetime.now(timezone.utc)
    created = 0
    llm_calls = 0
    stats = {"items": 0, "gap": 0, "cache_hit": 0, "llm_called": 0, "rule_claims": 0, "llm_claims": 0}
    for entry in feed.entries:
        ext = getattr(entry, "id", None) or getattr(entry, "link", None)
        if ext is None:
            continue
        if session.scalar(select(Item).where(Item.source_id == source.id, Item.external_id == ext)):
            continue
        text = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}"
        item = Item(source_id=source.id, external_id=ext, title=getattr(entry, "title", None),
                    text=text, url=getattr(entry, "link", None),
                    published_at=_published(entry), fetched_at=now)
        session.add(item); session.flush()
        created += 1; stats["items"] += 1

        rule_pcs = extract_claims(text, assets, sector_map=sector_map)
        if rule_pcs:
            for pc in rule_pcs:
                asset = by_symbol[pc.asset_symbol]
                try:
                    spot = get_spot_price(asset)
                except Exception as e:
                    logger.warning("skip rule claim %s: price failed: %s", pc.asset_symbol, e); continue
                _add_claim(session, source, item, asset.symbol, pc.direction, pc.confidence,
                           "rule", PARSER_VERSION, asdict(pc), text, spot, now)
                stats["rule_claims"] += 1
        else:
            stats["gap"] += 1
            if llm_calls >= _LLM_MAX_PER_RUN:
                continue
            # _gap_fill returns (triples, called): called=True only on a real LLM call (cache miss)
            triples, called = _gap_fill(session, text, assets, sector_map)
            if called:
                llm_calls += 1; stats["llm_called"] += 1
            else:
                stats["cache_hit"] += 1
            for sym, direction, reasoning in triples:
                asset = by_symbol.get(sym)
                if asset is None:
                    continue
                try:
                    spot = get_spot_price(asset)
                except Exception as e:
                    logger.warning("skip llm claim %s: price failed: %s", sym, e); continue
                _add_claim(session, source, item, sym, direction, LLM_DEFAULT_CONFIDENCE,
                           "llm", "llm-v1",
                           {"asset": sym, "direction": direction, "reasoning": reasoning},
                           text, spot, now)
                stats["llm_claims"] += 1
    session.commit()
    logger.info("collect_rss %s: %s", source.display_name, stats)
    return created
```
- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_rss.py` → all green (existing rule/dedup/sector tests + 3 new gap tests). Then full suite `... pytest -q`.

- [ ] **Step 5: Commit**
```
git add argus/argus/collectors/rss.py argus/tests/test_rss.py
git commit -m "feat(argus): collect_rss inline LLM gap-fill (cache-aware, capped, metrics log)"
```

---

### Task 6: `.env.example` — klucze + flagi LLM

**Files:** Modify `argus/.env.example`

- [ ] **Step 1: Append to `argus/.env.example`**
```
# --- LLM (Increment 6) — wstaw realne klucze w .env na VPS ---
GEMINI_API_KEY=
OPENROUTER_API_KEY=
ARGUS_LLM_ALLOW_PAID=false
ARGUS_LLM_PAID_MODEL=openai/gpt-4o-mini
ARGUS_LLM_MAX_PER_RUN=30
```

- [ ] **Step 2: Commit**
```
git add argus/.env.example
git commit -m "chore(argus): .env.example LLM keys + flags"
```
(`docker-compose.yml` już używa `env_file: .env` dla `app`, więc te zmienne automatycznie trafią do kontenera, gdy user wpisze je do `.env` na VPS.)

---

### Task 7: `/api/llm/usage` endpoint (monitoring kosztów/użycia)

**Files:** Modify `argus/argus/api.py`; Test `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing test to `argus/tests/test_api.py`**
```python
def test_llm_usage_aggregates():
    from datetime import datetime, timezone, timedelta
    from argus.models import LlmCall
    client, Sess = _client()
    s = Sess()
    now = datetime.now(timezone.utc)
    s.add(LlmCall(ts=now, provider="gemini", model="gemini-2.0-flash", tokens_in=100, tokens_out=50,
                  cost_usd=0.0, latency_ms=800, ok=True, error=None))
    s.add(LlmCall(ts=now, provider="gemini", model="gemini-2.0-flash", tokens_in=0, tokens_out=0,
                  cost_usd=0.0, latency_ms=500, ok=False, error="boom"))
    s.add(LlmCall(ts=now - timedelta(days=3), provider="openrouter", model="x:free", tokens_in=1, tokens_out=1,
                  cost_usd=0.0, latency_ms=100, ok=True, error=None))  # outside 24h
    s.commit()
    rows = client.get("/api/llm/usage?window=24h").json()
    gem = next(r for r in rows if r["model"] == "gemini-2.0-flash")
    assert gem["calls"] == 2 and gem["ok"] == 1
    assert gem["tokens_in"] == 100 and gem["tokens_out"] == 50
    assert all(r["model"] != "x:free" for r in rows)   # 3-day-old excluded
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_api.py -k llm_usage` → route missing.

- [ ] **Step 3: Edit `argus/argus/api.py`**
Add `case` to the sqlalchemy import (`from sqlalchemy import select, func, case`); add `LlmCall` to the models import line. Add this route after the liquidations routes, before the static mount (reuses `_LIQ_WINDOWS` for the window map):
```python
@app.get("/api/llm/usage")
async def llm_usage(window: str = "24h", session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    ok_sum = func.sum(case((LlmCall.ok == True, 1), else_=0))  # noqa: E712
    rows = session.execute(
        select(LlmCall.provider, LlmCall.model, func.count(), ok_sum,
               func.sum(LlmCall.tokens_in), func.sum(LlmCall.tokens_out),
               func.sum(LlmCall.cost_usd), func.avg(LlmCall.latency_ms))
        .where(LlmCall.ts >= since)
        .group_by(LlmCall.provider, LlmCall.model)).all()
    return sorted(
        [{"provider": p, "model": m, "calls": int(c), "ok": int(ok or 0),
          "tokens_in": int(ti or 0), "tokens_out": int(to or 0),
          "cost_usd": round(float(cost or 0), 6), "avg_latency_ms": int(lat or 0)}
         for p, m, c, ok, ti, to, cost, lat in rows],
        key=lambda r: -r["calls"])
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_api.py -k llm_usage` (1 passed), then WHOLE file `... pytest -q tests/test_api.py` (no regressions).

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/llm/usage (cost+usage per provider/model)"
```

---

### Task 8: Dashboard panel „LLM usage"

**Files:** Modify `argus/argus/web/index.html`; Modify `argus/argus/web/app.js` (manual verification)

- [ ] **Step 1: Read both web files** to append without breaking existing sections (overview, wallets, liquidations, detail).

- [ ] **Step 2: Add to `index.html`** before `<div id="detail" ...>`:
```html
<h2>LLM usage
  <select id="llmWin"><option>1h</option><option>4h</option><option selected>24h</option><option>7d</option></select>
</h2>
<table id="llmusage"></table>
```

- [ ] **Step 3: Append to `app.js`** (and call `loadLlmUsage()` at end of `loadOverview()`, + listener):
```javascript
async function loadLlmUsage(){
  const w = document.getElementById('llmWin').value;
  let rows = [];
  try { rows = await getJSON(`/api/llm/usage?window=${w}`); } catch(e){}
  document.getElementById('llmusage').innerHTML =
    '<tr><th>Provider</th><th>Model</th><th>Calls</th><th>OK%</th><th>Tok in</th><th>Tok out</th><th>Cost $</th><th>ms</th></tr>' +
    rows.map(r => `<tr><td>${r.provider}</td><td>${r.model}</td><td>${r.calls}</td>`+
      `<td>${r.calls?Math.round(100*r.ok/r.calls):0}</td><td>${r.tokens_in}</td><td>${r.tokens_out}</td>`+
      `<td>${r.cost_usd.toFixed(4)}</td><td>${r.avg_latency_ms}</td></tr>`).join('');
}
document.getElementById('llmWin').addEventListener('change', loadLlmUsage);
```
Add `loadLlmUsage();` at the end of `loadOverview()`.

- [ ] **Step 4: Commit**
```
git add argus/argus/web/index.html argus/argus/web/app.js
git commit -m "feat(argus): dashboard LLM usage panel"
```

---

### Task 9: Spike LLM z VPS (prerequisite: klucze w .env)

**Files:** Create `argus/docs/llm-spike-findings.md`

> Ten task uruchamia agent z dostępem do VPS. **Wymaga, by user wstawił `GEMINI_API_KEY` i `OPENROUTER_API_KEY` do `~/argus/.env` na VPS.** Jeśli kluczy brak → BLOCKED, poproś usera.

- [ ] **Step 1: Sprawdź obecność kluczy na VPS**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new ubuntu@84.235.174.129 "cd ~/argus && grep -c -E 'GEMINI_API_KEY=.+|OPENROUTER_API_KEY=.+' .env"
```
Jeśli 0 → BLOCKED (user musi dodać klucze).

- [ ] **Step 2: Test Gemini free + JSON na realnym promptcie** (klucz z .env, na VPS):
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && set -a && . ./.env && set +a && curl -sS \"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=\$GEMINI_API_KEY\" -H 'Content-Type: application/json' -d '{\"contents\":[{\"parts\":[{\"text\":\"Zwroc WYLACZNIE JSON: [{\\\"asset\\\":\\\"BTC\\\",\\\"direction\\\":\\\"bull|bear\\\",\\\"reasoning\\\":\\\"...\\\"}]. Tekst: Fed signals dovish pivot, risk assets rally.\"}]}]}' | head -c 600"
```
Zapisz odpowiedź. Sprawdź czy zwraca parsowalny JSON (ew. w ```json fence — ekstraktor to obsługuje).

- [ ] **Step 3: (jeśli OpenRouter key jest) krótki test OpenRouter free** analogicznie (POST do `https://openrouter.ai/api/v1/chat/completions`, model `meta-llama/llama-3.3-70b-instruct:free`).

- [ ] **Step 4: Zapisz `argus/docs/llm-spike-findings.md`** — czy Gemini/OpenRouter free osiągalne z VPS, czy JSON parsowalny, format odpowiedzi (fence?), latencja. Flaguj jeśli model uparcie dodaje prozę zamiast JSON (wtedy prompt do dostrojenia).

- [ ] **Step 5: Commit**
```
git add argus/docs/llm-spike-findings.md
git commit -m "chore(argus): LLM spike findings (free model JSON from VPS)"
```

---

### Task 10: Redeploy + smoke

**Files:** (deployment)

- [ ] **Step 1: Copy + rebuild — PRESERVE the VPS `.env` (it holds the real LLM keys; the local one has placeholders).**
Backup the VPS `.env`, scp the code, restore the `.env`, then rebuild:
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new ubuntu@84.235.174.129 "cp ~/argus/.env /tmp/argus.env.keep"
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cp /tmp/argus.env.keep ~/argus/.env && cd ~/argus && docker compose up -d --build"
```
This guarantees the keys the user placed in the VPS `.env` survive the redeploy.

- [ ] **Step 2: Smoke (after ~25s)** — trigger rss job once, sprawdź czy powstają llm-claimy + metryki:
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 25 && curl -sS http://localhost:8080/health; echo; cd ~/argus && docker compose exec -T app python -c \"
from argus.main import _rss_job
from argus.db import SessionLocal
from argus.models import Claim
from sqlalchemy import select, func
_rss_job()
s = SessionLocal()
print('claims by method:', dict(s.execute(select(Claim.method, func.count()).group_by(Claim.method)).all()))
\"; echo '--- collect_rss metric logs ---'; docker compose logs --since 3m app | grep -i 'collect_rss' | tail -10; echo '--- llm usage ---'; curl -sS 'http://localhost:8080/api/llm/usage?window=24h'"
```
Expected: health ok; `claims by method` zawiera `llm` > 0 (jeśli były luki + LLM zwrócił coś); logi `collect_rss ...: {'items':..,'gap':..,'cache_hit':..,'llm_called':..}`; `/api/llm/usage` pokazuje wiersze per provider/model z tokenami/kosztem (też darmowe = cost 0). Jeśli `llm`=0 / usage puste — sprawdź logi pod kątem błędów klucza/JSON (acceptable jeśli akurat brak luk z powiązaniem; re-check).

- [ ] **Step 3: Note for user** — weryfikacja przez tunel; claimy `method=llm` w drill-downie aktywa (reasoning w claim_audit).

---

## Self-Review

**Spec coverage:**
- Router free→paid gated (Gemini/OpenRouter), klucze env → Task 2 ✅
- **Monitoring: każde wywołanie (też free/fail) → `llm_calls`; `/api/llm/usage` + panel** → Task 1 (LlmCall) + Task 2 (_record/_cost) + Task 7 (endpoint) + Task 8 (panel) ✅
- Ekstraktor: wąski prompt + grounding gate, walidacja watchlisty, stałe confidence 0.35, reasoning → Task 3 ✅
- LLM NIE zwraca confidence (kod nadaje 0.35) → Task 3 ✅
- Gap-fill INLINE w collect_rss (bez joba/tabeli processed) → Task 5 ✅
- Cache po text_hash, też puste wyniki (rola „processed") → Task 1+4+5 ✅
- method="llm", parser_version="llm-v1", reasoning w ClaimAudit → Task 5 ✅
- Per-run cap (ARGUS_LLM_MAX_PER_RUN) + ALLOW_PAID gate → Task 2+5+6 ✅
- Metryki log (gap/cache_hit/llm_called/...) → Task 5 ✅
- Klucze prerequisite + spike z VPS → Task 6+9 ✅
- Judge — odłożony (brak zadania, świadomie) ✅
- Redeploy + smoke (z /api/llm/usage) → Task 10 ✅

**Uproszczenie vs spec:** brak osobnego metering USD poza `llm_calls` — koszt liczony per-call z cennika (`_cost`, free=0), agregowany w `/api/llm/usage`. Kontrola kosztów = cache + ALLOW_PAID(off) + per-run cap.

**Placeholder scan:** brak — pełny kod w każdym kroku.

**Type consistency:** `call_llm(prompt, system, max_tokens)` (Task 2) ↔ extractor (Task 3); `_gemini`/`_openrouter` zwracają `(text, usage)`, `_record(provider,model,usage,latency_ms,ok,error)`, `_cost(model,usage)` (Task 2) ↔ testy. `extract_claims_llm(text, assets, sector_map)->list[LlmClaim]` (Task 3) ↔ collect_rss (Task 5). `LlmClaim(asset_symbol,direction,confidence,reasoning)` spójny. `cache_get->list|None`, `cache_put`, `text_hash` (Task 4) ↔ `_gap_fill` (Task 5). `LlmCache`/`LlmCall` (Task 1) ↔ cache.py (Task 4) + router `_record` (Task 2) + `/api/llm/usage` (Task 7). `_LIQ_WINDOWS` reużyte w `/api/llm/usage` (Task 7).
