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
        fallback_api_key: str | None = None,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
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

        self.fallback_model = fallback_model
        self._fallback_client = None
        if fallback_api_key:
            self._fallback_client = httpx.AsyncClient(
                base_url=(fallback_base_url or OPENROUTER_BASE),
                headers={
                    "Authorization": f"Bearer {fallback_api_key}",
                    "HTTP-Referer": "http://localhost:3003",
                    "X-Title": "RAG System",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 429
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))

    async def _post_with_fallback(self, payload: dict) -> dict:
        """POST /chat/completions on primary, retrying once on fallback for retryable errors."""
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if not (self._fallback_client and self._is_retryable(exc)):
                raise
            logger.warning("OpenRouter primary failed (%s), retrying on fallback", exc)

        fallback_payload = {**payload, "model": self.fallback_model or self.model}
        resp = await self._fallback_client.post("/chat/completions", json=fallback_payload)
        resp.raise_for_status()
        return resp.json()

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

        yielded_any = False
        try:
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
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if token:
                        yielded_any = True
                        yield token
                return
        except Exception as exc:
            if yielded_any or not (self._fallback_client and self._is_retryable(exc)):
                raise
            logger.warning("OpenRouter primary failed (%s), retrying on fallback", exc)

        fallback_payload = {**payload, "model": self.fallback_model or self.model}
        async with self._fallback_client.stream("POST", "/chat/completions", json=fallback_payload) as resp:
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

        data = await self._post_with_fallback(payload)

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

        data = await self._post_with_fallback(payload)

        text = data["choices"][0]["message"]["content"]
        return GenerationResult(text=text, model=data.get("model", self.model))

    async def close(self):
        await self._client.aclose()
        if self._fallback_client:
            await self._fallback_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
