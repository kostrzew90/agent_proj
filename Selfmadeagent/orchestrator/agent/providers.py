import os
import time
import litellm
from dataclasses import dataclass
from langfuse.decorators import observe

# Suppress LiteLLM debug logs
litellm.suppress_debug_info = True


@dataclass
class ProviderConfig:
    model: str
    api_base: str | None = None
    api_key: str | None = None
    provider: str = "unknown"


def get_provider_chain() -> list[ProviderConfig]:
    """Build provider fallback chain from env vars.

    Order: Ollama → OpenRouter → OpenAI → Anthropic.
    Only includes providers that have required config set.
    """
    chain = []

    # Allow runtime model override without changing .env
    model_override = os.getenv("MODEL_OVERRIDE")

    # Ollama (default primary)
    ollama_model = os.getenv("OLLAMA_MODEL")
    ollama_base = os.getenv("OLLAMA_API_BASE")
    if ollama_model and ollama_base:
        chain.append(ProviderConfig(
            model=f"ollama/{model_override or ollama_model}",
            api_base=ollama_base,
            provider="ollama",
        ))

    # OpenRouter
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openrouter_model = os.getenv("OPENROUTER_MODEL")
    if openrouter_key and openrouter_model:
        chain.append(ProviderConfig(
            model=f"openrouter/{openrouter_model}",
            api_key=openrouter_key,
            provider="openrouter",
        ))

    # OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL")
    if openai_key and openai_model:
        chain.append(ProviderConfig(
            model=openai_model,
            api_key=openai_key,
            provider="openai",
        ))

    # Anthropic
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model = os.getenv("ANTHROPIC_MODEL")
    if anthropic_key and anthropic_model:
        chain.append(ProviderConfig(
            model=anthropic_model,
            api_key=anthropic_key,
            provider="anthropic",
        ))

    return chain


def _record_llmops(provider: ProviderConfig, t0: float, response=None, error=None) -> None:
    try:
        from agent import llmops_client
        usage = getattr(response, "usage", None)
        llmops_client.record(
            provider=provider.provider,
            model=provider.model,
            call_type="generate",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            ok=error is None,
            error=(str(error) if error else None),
        )
    except Exception:
        pass


@observe(name="llm_call")
async def call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    provider_chain: list[ProviderConfig] | None = None,
) -> dict:
    """Call LLM with automatic fallback through provider chain.

    Returns the LiteLLM response dict.
    Raises Exception if all providers fail.
    """
    if provider_chain is None:
        provider_chain = get_provider_chain()

    if not provider_chain:
        raise RuntimeError("No LLM providers configured. Set OLLAMA_MODEL + OLLAMA_API_BASE in .env")

    last_error = None
    for provider in provider_chain:
        t0 = time.monotonic()
        try:
            kwargs = {
                "model": provider.model,
                "messages": messages,
            }
            if provider.api_base:
                kwargs["api_base"] = provider.api_base
            if provider.api_key:
                kwargs["api_key"] = provider.api_key
            if tools:
                kwargs["tools"] = tools

            response = await litellm.acompletion(**kwargs)
            _record_llmops(provider, t0, response=response)
            return response
        except Exception as e:
            last_error = e
            _record_llmops(provider, t0, error=e)
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
