import asyncio

from agent.providers import ProviderConfig, call_llm
import agent.llmops_client as llmops


class FakeUsage:
    prompt_tokens = 42
    completion_tokens = 13


class FakeResponse:
    usage = FakeUsage()


def test_successful_call_is_recorded(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))

    async def fake_acompletion(**kwargs):
        return FakeResponse()

    monkeypatch.setattr("agent.providers.litellm.acompletion", fake_acompletion)
    chain = [ProviderConfig(model="openrouter/qwen", provider="openrouter")]

    asyncio.run(call_llm([{"role": "user", "content": "hej"}], provider_chain=chain))

    assert len(sent) == 1
    assert sent[0]["provider"] == "openrouter"
    assert sent[0]["tokens_in"] == 42
    assert sent[0]["ok"] is True


def test_failed_provider_is_recorded_before_fallback(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))

    async def fake_acompletion(**kwargs):
        if kwargs["model"] == "ollama/a":
            raise RuntimeError("ollama down")
        return FakeResponse()

    monkeypatch.setattr("agent.providers.litellm.acompletion", fake_acompletion)
    chain = [ProviderConfig(model="ollama/a", provider="ollama"),
             ProviderConfig(model="openrouter/b", provider="openrouter")]

    asyncio.run(call_llm([{"role": "user", "content": "hej"}], provider_chain=chain))

    assert [s["ok"] for s in sent] == [False, True]
    assert sent[0]["provider"] == "ollama"
