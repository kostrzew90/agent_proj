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
    assert ("gemini", False) in rec and ("openrouter", True) in rec
