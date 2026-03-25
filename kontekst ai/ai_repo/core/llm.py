"""LLM client — Ollama primary, Anthropic fallback."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from ai_repo.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM interface — Ollama or Anthropic."""

    def __init__(self, db=None, purpose: str = "query"):
        self.provider = settings.llm.provider
        self.temperature = settings.llm.temperature
        self.max_tokens = settings.llm.max_tokens

        # Ollama settings
        self.ollama_url = settings.ollama.url.rstrip("/")
        self.ollama_model = settings.ollama.llm_model
        self.ollama_timeout = settings.ollama.timeout

        # Anthropic settings
        self.anthropic_key = settings.llm.anthropic_api_key
        self._anthropic_client = None

        # Metrics
        self._db = db
        self._purpose = purpose

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a complete response (non-streaming)."""
        import time

        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens or self.max_tokens
        t0 = time.time()

        try:
            if self.provider == "anthropic" and self.anthropic_key:
                result = await self._generate_anthropic(prompt, system, temp, tokens)
                self._record("anthropic", "claude-sonnet-4-20250514", t0, prompt, result)
                return result
            # _generate_ollama may internally fallback to Anthropic
            result = await self._generate_ollama(prompt, system, temp, tokens)
            # Record happens after success — provider may have been ollama or anthropic (fallback)
            self._record("ollama", self.ollama_model, t0, prompt, result)
            return result
        except Exception as e:
            provider = "anthropic" if (self.provider == "anthropic" and self.anthropic_key) else "ollama"
            model = "claude-sonnet-4-20250514" if provider == "anthropic" else self.ollama_model
            self._record(provider, model, t0, prompt, "", success=False, error=str(e))
            raise

    async def generate_stream(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Generate response as a stream of text chunks."""
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens or self.max_tokens

        if self.provider == "anthropic" and self.anthropic_key:
            async for chunk in self._stream_anthropic(prompt, system, temp, tokens):
                yield chunk
        else:
            async for chunk in self._stream_ollama(prompt, system, temp, tokens):
                yield chunk

    # ── Metrics ─────────────────────────────────────────────────────────

    def _record(
        self, provider: str, model: str, t0: float,
        prompt: str, result: str,
        success: bool = True, error: Optional[str] = None,
    ):
        """Record LLM call metrics if db is available."""
        if not self._db:
            return
        import time

        try:
            from ai_repo.core.metrics import record_llm_call

            latency_ms = (time.time() - t0) * 1000
            # Rough token estimation (~4 chars/token)
            input_tokens = len(prompt) // 4
            output_tokens = len(result) // 4 if result else 0

            record_llm_call(
                self._db,
                provider=provider,
                model=model,
                purpose=self._purpose,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                success=success,
                error_msg=error,
            )
        except Exception:
            pass

    # ── Ollama ──────────────────────────────────────────────────────────

    async def _generate_ollama(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> str:
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.ollama_timeout) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate", json=payload
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama generate error: {e}")
            # Fallback to Anthropic if available
            if self.anthropic_key:
                logger.info("Falling back to Anthropic")
                if self._db:
                    try:
                        from ai_repo.core.metrics import emit_event
                        emit_event(
                            self._db, "llm", "warning",
                            f"Ollama failed ({e}), falling back to Anthropic",
                        )
                    except Exception:
                        pass
                return await self._generate_anthropic(
                    prompt, system, temperature, max_tokens
                )
            raise

    async def _stream_ollama(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.ollama_timeout) as client:
                async with client.stream(
                    "POST", f"{self.ollama_url}/api/generate", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                yield token
                            if data.get("done", False):
                                break
        except Exception as e:
            logger.error(f"Ollama stream error: {e}")
            if self.anthropic_key:
                async for chunk in self._stream_anthropic(
                    prompt, system, temperature, max_tokens
                ):
                    yield chunk

    # ── Anthropic ───────────────────────────────────────────────────────

    async def _generate_anthropic(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> str:
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
            messages = [{"role": "user", "content": prompt}]
            kwargs = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            response = await client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic generate error: {e}")
            raise

    async def _stream_anthropic(
        self, prompt: str, system: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
            messages = [{"role": "user", "content": prompt}]
            kwargs = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Anthropic stream error: {e}")
            raise
