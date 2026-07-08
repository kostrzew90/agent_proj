import time
from unittest.mock import patch
import pytest
import argus.llm.router as router

@pytest.fixture(autouse=True)
def _isolate_router_env(monkeypatch):
    # Deterministic regardless of host/container env: no groq unless a test
    # explicitly sets GROQ_KEY, and no leftover cooldowns between tests.
    monkeypatch.setattr(router, "GROQ_KEY", "")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()

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

def test_is_server_error_detects_503():
    class FakeResp:
        status_code = 503
    class FakeExc(Exception):
        response = FakeResp()
    assert router._is_server_error(FakeExc())
    assert not router._is_429(FakeExc())

def test_503_triggers_90s_cooldown():
    state = router._ProviderState(rpm=10)
    assert state.available()
    import httpx
    exc = httpx.HTTPStatusError("503", request=None, response=type("R", (), {"status_code": 503})())
    state.record_5xx()
    assert not state.available()
    assert state.seconds_until_free() >= 88  # ~90s

def test_503_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)
    # reset provider states so no leftover cooldown
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    class FakeResp:
        status_code = 503
    class Http503(Exception):
        response = FakeResp()
    with patch.object(router, "_gemini", side_effect=Http503("503 Service Unavailable")), \
         patch.object(router, "_openrouter", return_value=("OR-OK", {"tokens_in": 3, "tokens_out": 3})):
        result = router.call_llm("p")
    assert result == "OR-OK"
    assert router._STATES["gemini"].seconds_until_free() >= 80

def test_records_each_attempt(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    # reset provider states so no leftover cooldown from prior tests
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    rec = []
    monkeypatch.setattr(router, "_record", lambda provider, model, usage, latency_ms, ok, error: rec.append((provider, ok)))
    with patch.object(router, "_gemini", side_effect=RuntimeError("g")), \
         patch.object(router, "_openrouter", return_value=("hi", {"tokens_in": 2, "tokens_out": 2})):
        router.call_llm("p")
    assert ("gemini", False) in rec and ("openrouter", True) in rec

def test_gemini_fails_groq_succeeds(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "GROQ_KEY", "k")
    monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    rec = []
    monkeypatch.setattr(router, "_record", lambda provider, model, usage, latency_ms, ok, error: rec.append((provider, ok)))
    with patch.object(router, "_gemini", side_effect=RuntimeError("down")), \
         patch.object(router, "_groq", return_value=("OK-GROQ", {"tokens_in": 4, "tokens_out": 6})) as grm, \
         patch.object(router, "_openrouter") as orm:
        assert router.call_llm("p") == "OK-GROQ"
        assert grm.called
        assert not orm.called
    assert ("gemini", False) in rec and ("groq", True) in rec

def test_gemini_and_groq_fail_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "GROQ_KEY", "k")
    monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)

    class FakeResp:
        status_code = 429
    class Http429(Exception):
        response = FakeResp()

    with patch.object(router, "_gemini", side_effect=RuntimeError("down")), \
         patch.object(router, "_groq", side_effect=Http429("429")), \
         patch.object(router, "_openrouter", return_value=("OK-OR", {"tokens_in": 5, "tokens_out": 7})) as orm:
        assert router.call_llm("p") == "OK-OR"
        assert orm.called
    assert router._STATES["groq"].seconds_until_free() >= 55

def test_groq_not_attempted_without_key(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "GROQ_KEY", "")
    monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    rec = []
    monkeypatch.setattr(router, "_record", lambda provider, model, usage, latency_ms, ok, error: rec.append(provider))
    with patch.object(router, "_gemini", side_effect=RuntimeError("down")), \
         patch.object(router, "_groq") as grm, \
         patch.object(router, "_openrouter", return_value=("OK-OR", {"tokens_in": 1, "tokens_out": 1})):
        assert router.call_llm("p") == "OK-OR"
        assert not grm.called
    assert "groq" not in rec

def test_groq_respects_rate_limiter(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "GROQ_KEY", "k")
    monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    router._STATES["groq"]._blocked_until = time.time() + 30
    monkeypatch.setattr(router, "_record", lambda *a, **k: None)
    with patch.object(router, "_gemini", side_effect=RuntimeError("down")), \
         patch.object(router, "_groq") as grm, \
         patch.object(router, "_openrouter", return_value=("OK-OR", {"tokens_in": 1, "tokens_out": 1})):
        assert router.call_llm("p") == "OK-OR"
        assert not grm.called

def test_record_sanitizes_api_key_in_error(monkeypatch):
    monkeypatch.setattr(router, "GEMINI_KEY", "k"); monkeypatch.setattr(router, "OPENROUTER_KEY", "k")
    for s in router._STATES.values():
        s._blocked_until = 0.0; s._streak = 0; s._window.clear()
    recorded_errors = []
    monkeypatch.setattr(router, "_record",
        lambda provider, model, usage, latency_ms, ok, error: recorded_errors.append(error))
    leaky = RuntimeError(
        "Client error '429' for url "
        "'https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=AIzaSyD7q1Xlj1hQwPwoQWKtPHzq-LXS9AshA-U'"
    )
    with patch.object(router, "_gemini", side_effect=leaky), \
         patch.object(router, "_openrouter", return_value=("hi", {"tokens_in": 1, "tokens_out": 1})):
        router.call_llm("p")
    assert recorded_errors  # gemini's failure was recorded
    gemini_error = recorded_errors[0]
    assert "AIzaSyD7q1Xlj1hQwPwoQWKtPHzq-LXS9AshA-U" not in gemini_error
    assert "key=***" in gemini_error
