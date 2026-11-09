from ai_repo.core.llm import LLMClient
import ai_repo.core.llmops_client as llmops


def test_record_emits_even_without_local_db(monkeypatch):
    """kontekst-ai wychodzi wczesniej z _record, gdy nie ma self._db.
    Telemetria centralna nie moze na tym tracic."""
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    client = LLMClient(db=None, purpose="query")
    client._record("anthropic", "claude-sonnet-4-20250514", 0.0, "pytanie", "odpowiedz")
    assert len(sent) == 1
    assert sent[0]["provider"] == "anthropic"
    assert sent[0]["tokens_estimated"] is True
