import core.llmops_client as llmops
from core.llmops_emit import emit_llmops_calls


def test_emits_one_row_per_call_record(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    records = [
        {"call_type": "rewrite", "provider": "openrouter", "model": "m1",
         "tokens_in": 10, "tokens_out": 5, "latency_ms": 100},
        {"call_type": "generate", "provider": "ollama", "model": "m2",
         "tokens_in": 900, "tokens_out": 300, "latency_ms": 2000},
    ]
    emit_llmops_calls(records)
    assert [s["call_type"] for s in sent] == ["rewrite", "generate"]
    assert sent[1]["model"] == "m2"
    assert sent[1]["ok"] is True


def test_emission_survives_broken_record(monkeypatch):
    """Jeden zepsuty wpis nie moze zabrac pozostalych ani wywalic odpowiedzi."""
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    records = [
        {"nonsens": True},
        {"call_type": "judge", "provider": "openrouter", "model": "m3",
         "tokens_in": 1, "tokens_out": 1, "latency_ms": 10},
    ]
    emit_llmops_calls(records)
    assert len(sent) == 1
    assert sent[0]["call_type"] == "judge"
