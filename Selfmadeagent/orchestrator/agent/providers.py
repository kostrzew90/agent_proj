import os
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


def get_provider_chain() -> list[ProviderConfig]:
    """Build provider fallback chain from env vars.

    Order: Ollama → OpenRouter → OpenAI → Anthropic.
    Only includes providers that have required config set.
    """
    chain = []

    # Ollama (default primary)
    ollama_model = os.getenv("OLLAMA_MODEL")
    ollama_base = os.getenv("OLLAMA_API_BASE")
    if ollama_model and ollama_base:
        chain.append(ProviderConfig(
            model=f"ollama/{ollama_model}",
            api_base=ollama_base,
        ))

    # OpenRouter
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openrouter_model = os.getenv("OPENROUTER_MODEL")
    if openrouter_key and openrouter_model:
        chain.append(ProviderConfig(
            model=f"openrouter/{openrouter_model}",
            api_key=openrouter_key,
        ))

    # OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL")
    if openai_key and openai_model:
        chain.append(ProviderConfig(
            model=openai_model,
            api_key=openai_key,
        ))

    # Anthropic
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model = os.getenv("ANTHROPIC_MODEL")
    if anthropic_key and anthropic_model:
        chain.append(ProviderConfig(
            model=anthropic_model,
            api_key=anthropic_key,
        ))

    return chain


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
            return response
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
