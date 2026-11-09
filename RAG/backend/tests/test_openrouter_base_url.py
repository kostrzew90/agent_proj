"""OpenRouterClient must accept a custom base_url (Gemini OpenAI-compat endpoint)."""
from core.openrouter import OpenRouterClient, OPENROUTER_BASE

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def test_default_base_url_unchanged():
    client = OpenRouterClient(api_key="k", model="m")
    assert str(client._client.base_url).rstrip("/") == OPENROUTER_BASE.rstrip("/")


def test_custom_base_url():
    client = OpenRouterClient(api_key="k", model="m", base_url=GEMINI_BASE)
    assert str(client._client.base_url).rstrip("/") == GEMINI_BASE


def test_empty_base_url_falls_back_to_default():
    client = OpenRouterClient(api_key="k", model="m", base_url="")
    assert str(client._client.base_url).rstrip("/") == OPENROUTER_BASE.rstrip("/")
