"""
RAG System — OpenRouter LLM Client
OpenAI-compatible API, drop-in replacement for AsyncLLMClient.
Docs: https://openrouter.ai/docs
"""

import json
import logging
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger("rag.core.openrouter")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    """
    Async OpenRouter client compatible with AsyncLLMClient interface.
    Uses OpenAI streaming format (SSE with delta.content).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        base_url: str | None = None,
    ):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=(base_url or OPENROUTER_BASE),
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "http://localhost:3003",
                "X-Title": "RAG System",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        **_,
    ) -> AsyncIterator[str]:
        """Streaming generation — yields text tokens."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        **_,
    ) -> "GenerationResult":
        """Non-streaming generation (for judge)."""
        from core.llm import GenerationResult

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return GenerationResult(
            text=text,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
        **_,
    ) -> "GenerationResult":
        """Non-streaming chat (for rewriter)."""
        from core.llm import GenerationResult

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        text = data["choices"][0]["message"]["content"]
        return GenerationResult(text=text, model=data.get("model", self.model))

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
