"""
RAG System — Ollama LLM Client
Provides sync and async streaming generation via Ollama API.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, Optional

import httpx

from config import settings

logger = logging.getLogger("rag.core.llm")


@dataclass
class GenerationResult:
    """Complete (non-streaming) generation result."""
    text: str
    model: str = ""
    total_duration_ms: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    done: bool = True


class LLMClient:
    """Synchronous Ollama LLM client (for Celery workers / judge)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 600.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.llm_model
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> GenerationResult:
        """Non-streaming generation. Returns complete result."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        resp = self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return GenerationResult(
            text=data.get("response", ""),
            model=data.get("model", self.model),
            total_duration_ms=data.get("total_duration", 0) / 1_000_000,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> GenerationResult:
        """Non-streaming chat completion."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        resp = self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return GenerationResult(
            text=data.get("message", {}).get("content", ""),
            model=data.get("model", self.model),
            total_duration_ms=data.get("total_duration", 0) / 1_000_000,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncLLMClient:
    """Async Ollama LLM client with streaming (for FastAPI SSE endpoints)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 600.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.llm_model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Streaming generation — yields text tokens as they arrive."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        async with self._client.stream("POST", "/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done", False):
                    return

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Streaming chat — yields text tokens."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done", False):
                    return

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        think: bool = False,
    ) -> GenerationResult:
        """Non-streaming async generation."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        resp = await self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return GenerationResult(
            text=data.get("response", ""),
            model=data.get("model", self.model),
            total_duration_ms=data.get("total_duration", 0) / 1_000_000,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> GenerationResult:
        """Non-streaming async chat."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return GenerationResult(
            text=data.get("message", {}).get("content", ""),
            model=data.get("model", self.model),
            total_duration_ms=data.get("total_duration", 0) / 1_000_000,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return self.model in models
        except Exception as e:
            logger.warning(f"Ollama LLM health check failed: {e}")
            return False

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def get_judge_client() -> LLMClient:
    """Get sync LLM client configured for the judge model."""
    return LLMClient(model=settings.ai.judge_model)
