"""Ollama embedding client — batch processing with retry."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ai_repo.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Generate embeddings via Ollama's /api/embed endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        timeout: Optional[int] = None,
        db=None,
    ):
        self.base_url = (base_url or settings.ollama.url).rstrip("/")
        self.model = model or settings.ollama.embed_model
        self.batch_size = batch_size or settings.ollama.embed_batch_size
        self.timeout = timeout or settings.ollama.timeout
        self._available: Optional[bool] = None
        self._db = db

    async def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        if self._available is not None:
            return self._available
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    async def embed_one(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text."""
        results = await self.embed_batch([text])
        return results[0] if results else None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Generate embeddings for a batch of texts.

        Returns list of embeddings (or None for failures), same length as input.
        """
        import time

        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start:batch_start + self.batch_size]
            t0 = time.time()

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/embed",
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    embeddings = data.get("embeddings", [])
                    for i, emb in enumerate(embeddings):
                        results[batch_start + i] = emb

            except httpx.TimeoutException:
                logger.warning(
                    f"Embedding timeout for batch starting at {batch_start}"
                )
                self._emit_error(
                    f"Embedding timeout for batch at {batch_start}",
                    "TimeoutError",
                )
            except Exception as e:
                logger.error(f"Embedding error: {e}")
                self._emit_error(f"Embedding error: {e}", type(e).__name__)

        return results

    def _emit_error(self, message: str, signature: str):
        """Emit an error event if db is available."""
        if self._db:
            try:
                from ai_repo.core.metrics import emit_event
                emit_event(self._db, "embeddings", "error", message, signature=signature)
            except Exception:
                pass

    def embed_one_sync(self, text: str) -> Optional[list[float]]:
        """Synchronous embedding for a single text."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": [text]},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings", [])
                return embeddings[0] if embeddings else None
        except Exception as e:
            logger.error(f"Sync embedding error: {e}")
            return None

    def embed_batch_sync(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Synchronous batch embedding."""
        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start:batch_start + self.batch_size]

            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{self.base_url}/api/embed",
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    embeddings = data.get("embeddings", [])
                    for i, emb in enumerate(embeddings):
                        results[batch_start + i] = emb

            except Exception as e:
                logger.error(f"Sync batch embedding error: {e}")
                self._emit_error(f"Sync batch error: {e}", type(e).__name__)

        return results
