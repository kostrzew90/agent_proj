"""
RAG System — Ollama Embedding Client
Provides sync and async methods for generating embeddings via Ollama API.
"""

import asyncio
import json
import logging
import statistics
import time
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
        timeout: float = 900.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.embedding_model
        self.dimension = settings.ai.embedding_dimension
        self.last_run_metrics: Optional[dict] = None
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text string. Returns vector of floats."""
        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Handles chunking into sub-batches."""
        all_vectors = []
        batch_latencies: list[float] = []
        total_chars = 0
        total_chunks = 0
        total_batches = max(1, (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE)
        batch_num = 0
        prev_latency: Optional[float] = None

        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            batch_chars = sum(len(t) for t in batch)
            t0 = time.monotonic()
            vectors = self._call_embed(batch)
            latency = time.monotonic() - t0
            throughput = batch_chars / latency if latency > 0 else 0.0

            logger.info(json.dumps({
                "evt": "embed_batch",
                "model": self.model,
                "batch_idx": i,
                "batch_num": batch_num,
                "total_batches": total_batches,
                "batch_size": len(batch),
                "chars": batch_chars,
                "latency_s": round(latency, 2),
                "throughput_chars_per_s": int(throughput),
            }))

            if prev_latency is not None and prev_latency > 0:
                ratio = latency / prev_latency
                if ratio > 2.0:
                    logger.warning(json.dumps({
                        "evt": "embed_degradation",
                        "model": self.model,
                        "batch_idx": i,
                        "prev_latency_s": round(prev_latency, 2),
                        "curr_latency_s": round(latency, 2),
                        "ratio": round(ratio, 2),
                    }))

            batch_latencies.append(latency)
            total_chars += batch_chars
            total_chunks += len(batch)
            prev_latency = latency
            batch_num += 1

            all_vectors.extend(vectors)

        # Summary metrics
        if batch_latencies:
            sum_latency = sum(batch_latencies)
            avg_latency = sum_latency / len(batch_latencies)
            sorted_latencies = sorted(batch_latencies)
            p50 = statistics.median(sorted_latencies)
            p95_idx = max(0, int(len(sorted_latencies) * 0.95) - 1)
            p95 = sorted_latencies[p95_idx]
            max_latency = sorted_latencies[-1]
            degradation_ratio = max_latency / avg_latency if avg_latency > 0 else 1.0
            throughput_chunks = total_chunks / sum_latency if sum_latency > 0 else 0.0

            summary = {
                "evt": "embed_summary",
                "model": self.model,
                "total_batches": len(batch_latencies),
                "total_chunks": total_chunks,
                "total_chars": total_chars,
                "total_time_s": round(sum_latency, 2),
                "avg_latency_s": round(avg_latency, 2),
                "p50_latency_s": round(p50, 2),
                "p95_latency_s": round(p95, 2),
                "max_latency_s": round(max_latency, 2),
                "throughput_chunks_per_s": round(throughput_chunks, 2),
                "degradation_ratio": round(degradation_ratio, 2),
            }
            logger.info(json.dumps(summary))
            self.last_run_metrics = summary

        return all_vectors

    def _call_embed(self, texts: list[str]) -> list[list[float]]:
        """Single call to Ollama /api/embed with retry on transient errors."""
        _retry_sleeps = [5, 15, 45]
        last_exc: Optional[Exception] = None

        for attempt in range(1, 4):
            try:
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

            except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt <= 3:
                    sleep = _retry_sleeps[attempt - 1]
                    logger.warning(
                        f"Ollama embed retry {attempt}/3 after {sleep}s"
                        f" — {type(exc).__name__}: {exc}"
                    )
                    time.sleep(sleep)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    last_exc = exc
                    if attempt <= 3:
                        sleep = _retry_sleeps[attempt - 1]
                        logger.warning(
                            f"Ollama embed retry {attempt}/3 after {sleep}s"
                            f" — {type(exc).__name__}: {exc}"
                        )
                        time.sleep(sleep)
                else:
                    # 4xx — do not retry
                    raise

            except ValueError:
                raise

        raise last_exc  # type: ignore[misc]

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
        timeout: float = 900.0,
    ):
        self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
        self.model = model or settings.ai.embedding_model
        self.dimension = settings.ai.embedding_dimension
        self.last_run_metrics: Optional[dict] = None
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_vectors = []
        batch_latencies: list[float] = []
        total_chars = 0
        total_chunks = 0
        total_batches = max(1, (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE)
        batch_num = 0
        prev_latency: Optional[float] = None

        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            batch_chars = sum(len(t) for t in batch)
            t0 = time.monotonic()
            vectors = await self._call_embed(batch)
            latency = time.monotonic() - t0
            throughput = batch_chars / latency if latency > 0 else 0.0

            logger.info(json.dumps({
                "evt": "embed_batch",
                "model": self.model,
                "batch_idx": i,
                "batch_num": batch_num,
                "total_batches": total_batches,
                "batch_size": len(batch),
                "chars": batch_chars,
                "latency_s": round(latency, 2),
                "throughput_chars_per_s": int(throughput),
            }))

            if prev_latency is not None and prev_latency > 0:
                ratio = latency / prev_latency
                if ratio > 2.0:
                    logger.warning(json.dumps({
                        "evt": "embed_degradation",
                        "model": self.model,
                        "batch_idx": i,
                        "prev_latency_s": round(prev_latency, 2),
                        "curr_latency_s": round(latency, 2),
                        "ratio": round(ratio, 2),
                    }))

            batch_latencies.append(latency)
            total_chars += batch_chars
            total_chunks += len(batch)
            prev_latency = latency
            batch_num += 1

            all_vectors.extend(vectors)

        # Summary metrics
        if batch_latencies:
            sum_latency = sum(batch_latencies)
            avg_latency = sum_latency / len(batch_latencies)
            sorted_latencies = sorted(batch_latencies)
            p50 = statistics.median(sorted_latencies)
            p95_idx = max(0, int(len(sorted_latencies) * 0.95) - 1)
            p95 = sorted_latencies[p95_idx]
            max_latency = sorted_latencies[-1]
            degradation_ratio = max_latency / avg_latency if avg_latency > 0 else 1.0
            throughput_chunks = total_chunks / sum_latency if sum_latency > 0 else 0.0

            summary = {
                "evt": "embed_summary",
                "model": self.model,
                "total_batches": len(batch_latencies),
                "total_chunks": total_chunks,
                "total_chars": total_chars,
                "total_time_s": round(sum_latency, 2),
                "avg_latency_s": round(avg_latency, 2),
                "p50_latency_s": round(p50, 2),
                "p95_latency_s": round(p95, 2),
                "max_latency_s": round(max_latency, 2),
                "throughput_chunks_per_s": round(throughput_chunks, 2),
                "degradation_ratio": round(degradation_ratio, 2),
            }
            logger.info(json.dumps(summary))
            self.last_run_metrics = summary

        return all_vectors

    async def _call_embed(self, texts: list[str]) -> list[list[float]]:
        """Single call to Ollama /api/embed with retry on transient errors."""
        _retry_sleeps = [5, 15, 45]
        last_exc: Optional[Exception] = None

        for attempt in range(1, 4):
            try:
                resp = await self._client.post(
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

            except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt <= 3:
                    sleep = _retry_sleeps[attempt - 1]
                    logger.warning(
                        f"Ollama embed retry {attempt}/3 after {sleep}s"
                        f" — {type(exc).__name__}: {exc}"
                    )
                    await asyncio.sleep(sleep)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    last_exc = exc
                    if attempt <= 3:
                        sleep = _retry_sleeps[attempt - 1]
                        logger.warning(
                            f"Ollama embed retry {attempt}/3 after {sleep}s"
                            f" — {type(exc).__name__}: {exc}"
                        )
                        await asyncio.sleep(sleep)
                else:
                    # 4xx — do not retry
                    raise

            except ValueError:
                raise

        raise last_exc  # type: ignore[misc]

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
