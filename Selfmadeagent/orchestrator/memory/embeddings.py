"""Embedding client — Ollama /api/embed with batch support."""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_API_BASE", "http://mac-studio-artur.tail7896fa.ts.net:11434")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
EMBED_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


class EmbeddingClient:
    """Generate embeddings via Ollama's /api/embed endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dim: Optional[int] = None,
        batch_size: int = 32,
        timeout: int = 60,
    ):
        self.base_url = (base_url or OLLAMA_BASE).rstrip("/")
        self.model = model or EMBED_MODEL
        self.dim = dim or EMBED_DIM
        self.batch_size = batch_size
        self.timeout = timeout

    async def embed_one(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text."""
        results = await self.embed_batch([text])
        return results[0] if results else None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start:batch_start + self.batch_size]
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
                logger.warning(f"Embedding timeout for batch at {batch_start}")
            except Exception as e:
                logger.error(f"Embedding error: {e}")

        return results

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
