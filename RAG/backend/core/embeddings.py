"""
RAG System — Ollama Embedding Client
Provides sync and async methods for generating embeddings via Ollama API.
"""

import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("rag.core.embeddings")

# Ollama /api/embed accepts batch input natively
_BATCH_SIZE = 16  # max texts per request to avoid timeouts on large transcripts


class EmbeddingClient:
    """Synchronous Ollama embedding client (for Celery workers)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.embedding_model
        self.dimension = settings.ai.embedding_dimension
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text string. Returns vector of floats."""
        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Handles chunking into sub-batches."""
        all_vectors = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            vectors = self._call_embed(batch)
            all_vectors.extend(vectors)
        return all_vectors

    def _call_embed(self, texts: list[str]) -> list[list[float]]:
        """Single call to Ollama /api/embed."""
        resp = self._client.post(
            "/api/embed",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data["embeddings"]
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Expected {len(texts)} embeddings, got {len(embeddings)}"
            )
        return embeddings

    def health_check(self) -> bool:
        """Check if Ollama is reachable and model is available."""
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return self.model in models
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncEmbeddingClient:
    """Async Ollama embedding client (for FastAPI endpoints)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.embedding_model
        self.dimension = settings.ai.embedding_dimension
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_vectors = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            vectors = await self._call_embed(batch)
            all_vectors.extend(vectors)
        return all_vectors

    async def _call_embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/api/embed",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"]

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return self.model in models
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Module-level singleton for Celery workers
_sync_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """Get or create sync embedding client singleton."""
    global _sync_client
    if _sync_client is None:
        _sync_client = EmbeddingClient()
    return _sync_client
