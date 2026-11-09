"""
RAG System — Embedding Client
Provides sync and async methods for generating embeddings. Uses OpenRouter's
OpenAI-compatible /embeddings endpoint (google/gemini-embedding-001) when
OPENROUTER_API_KEY is set, otherwise falls back to a local Ollama /api/embed
— same provider-selection pattern as core/judge.py and core/rewriter.py.
"""

import asyncio
import json
import logging
import statistics
import time
from typing import Optional

import httpx

from config import settings
from core.openrouter import OPENROUTER_BASE

logger = logging.getLogger("rag.core.embeddings")

# Ollama: small batches avoid local-CPU timeouts. OpenRouter/Gemini: fewer,
# larger requests instead — free-tier quota is per-request-per-minute, not per-token.
_BATCH_SIZE_OLLAMA = 16
_BATCH_SIZE_OPENROUTER = 96
# Free-tier Gemini embeddings RPM is low enough that back-to-back batches trip
# 429 even with retries — pace proactively instead of only reacting to it.
_BATCH_PACING_OPENROUTER_S = 13


class EmbeddingClient:
    """Synchronous embedding client (for Celery workers)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 900.0,
    ):
        self.use_openrouter = bool(settings.ai.openrouter_api_key)
        headers = {}
        if self.use_openrouter:
            embed_key = settings.ai.openrouter_embedding_api_key or settings.ai.openrouter_api_key
            # NOTE: does NOT fall back to openrouter_base_url — that's the primary
            # LLM endpoint (may point straight at Gemini's own low-quota API).
            embed_base = settings.ai.openrouter_embedding_base_url or OPENROUTER_BASE
            self.base_url = (base_url or embed_base).rstrip("/")
            self.model = model or settings.ai.openrouter_embedding_model
            headers = {"Authorization": f"Bearer {embed_key}"}
            self.batch_size = _BATCH_SIZE_OPENROUTER
            self.batch_pacing_s = _BATCH_PACING_OPENROUTER_S
        else:
            self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
            self.model = model or settings.ai.embedding_model
            self.batch_size = _BATCH_SIZE_OLLAMA
            self.batch_pacing_s = 0
        self.dimension = settings.ai.embedding_dimension
        self.last_run_metrics: Optional[dict] = None
        # prompt tokens billed for the most recent embed_batch/embed_one call.
        # Safe only because the Celery worker using the module-level singleton
        # (get_embedding_client) runs with --concurrency=1 — raising concurrency
        # lets calls interleave and corrupt this shared counter silently.
        self.last_usage_tokens = 0
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

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
        total_batches = max(1, (len(texts) + self.batch_size - 1) // self.batch_size)
        batch_num = 0
        prev_latency: Optional[float] = None
        self.last_usage_tokens = 0

        for i in range(0, len(texts), self.batch_size):
            if i > 0 and self.batch_pacing_s:
                time.sleep(self.batch_pacing_s)
            batch = texts[i : i + self.batch_size]
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

            try:
                from core import llmops_client
                llmops_client.record(
                    provider="openrouter" if self.use_openrouter else "ollama",
                    model=self.model, call_type="embed",
                    tokens_in=self.last_usage_tokens, tokens_out=0,
                    latency_ms=int(sum_latency * 1000), ok=True,
                )
            except Exception:
                pass

        return all_vectors

    def _call_embed(self, texts: list[str]) -> list[list[float]]:
        """Single call to the embedding provider with retry on transient errors."""
        # 429 on OpenRouter/Gemini is a per-minute quota — short backoff won't clear it.
        _retry_sleeps = [10, 30, 65]
        last_exc: Optional[Exception] = None
        path = "/embeddings" if self.use_openrouter else "/api/embed"
        payload = (
            {"model": self.model, "input": texts, "dimensions": self.dimension}
            if self.use_openrouter
            else {"model": self.model, "input": texts}
        )

        for attempt in range(1, 4):
            try:
                resp = self._client.post(path, json=payload)
                resp.raise_for_status()
                data = resp.json()
                embeddings = (
                    [item["embedding"] for item in data["data"]]
                    if self.use_openrouter
                    else data["embeddings"]
                )
                if len(embeddings) != len(texts):
                    raise ValueError(
                        f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                    )
                if self.use_openrouter:
                    self.last_usage_tokens += data.get("usage", {}).get("total_tokens", 0)
                return embeddings

            except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt <= 3:
                    sleep = _retry_sleeps[attempt - 1]
                    logger.warning(
                        f"Embed retry {attempt}/3 after {sleep}s"
                        f" — {type(exc).__name__}: {exc}"
                    )
                    time.sleep(sleep)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 or exc.response.status_code == 429:
                    last_exc = exc
                    if attempt <= 3:
                        sleep = _retry_sleeps[attempt - 1]
                        logger.warning(
                            f"Embed retry {attempt}/3 after {sleep}s"
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
        """Check if the embedding provider is reachable and working."""
        try:
            self._call_embed(["health check"])
            return True
        except Exception as e:
            logger.warning(f"Embedding health check failed: {e}")
            return False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncEmbeddingClient:
    """Async embedding client (for FastAPI endpoints). See EmbeddingClient docstring for provider selection."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 900.0,
    ):
        self.use_openrouter = bool(settings.ai.openrouter_api_key)
        headers = {}
        if self.use_openrouter:
            embed_key = settings.ai.openrouter_embedding_api_key or settings.ai.openrouter_api_key
            # NOTE: does NOT fall back to openrouter_base_url — that's the primary
            # LLM endpoint (may point straight at Gemini's own low-quota API).
            embed_base = settings.ai.openrouter_embedding_base_url or OPENROUTER_BASE
            self.base_url = (base_url or embed_base).rstrip("/")
            self.model = model or settings.ai.openrouter_embedding_model
            headers = {"Authorization": f"Bearer {embed_key}"}
            self.batch_size = _BATCH_SIZE_OPENROUTER
            self.batch_pacing_s = _BATCH_PACING_OPENROUTER_S
        else:
            self.base_url = (base_url or settings.ai.ollama_url).rstrip("/")
            self.model = model or settings.ai.embedding_model
            self.batch_size = _BATCH_SIZE_OLLAMA
            self.batch_pacing_s = 0
        self.dimension = settings.ai.embedding_dimension
        self.last_run_metrics: Optional[dict] = None
        self.last_usage_tokens = 0  # prompt tokens billed for the most recent embed_batch/embed_one call
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=headers)

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_vectors = []
        batch_latencies: list[float] = []
        total_chars = 0
        total_chunks = 0
        total_batches = max(1, (len(texts) + self.batch_size - 1) // self.batch_size)
        batch_num = 0
        prev_latency: Optional[float] = None
        self.last_usage_tokens = 0

        for i in range(0, len(texts), self.batch_size):
            if i > 0 and self.batch_pacing_s:
                await asyncio.sleep(self.batch_pacing_s)
            batch = texts[i : i + self.batch_size]
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
        """Single call to the embedding provider with retry on transient errors."""
        # 429 on OpenRouter/Gemini is a per-minute quota — short backoff won't clear it.
        _retry_sleeps = [10, 30, 65]
        last_exc: Optional[Exception] = None
        path = "/embeddings" if self.use_openrouter else "/api/embed"
        payload = (
            {"model": self.model, "input": texts, "dimensions": self.dimension}
            if self.use_openrouter
            else {"model": self.model, "input": texts}
        )

        for attempt in range(1, 4):
            try:
                resp = await self._client.post(path, json=payload)
                resp.raise_for_status()
                data = resp.json()
                embeddings = (
                    [item["embedding"] for item in data["data"]]
                    if self.use_openrouter
                    else data["embeddings"]
                )
                if len(embeddings) != len(texts):
                    raise ValueError(
                        f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                    )
                if self.use_openrouter:
                    self.last_usage_tokens += data.get("usage", {}).get("total_tokens", 0)
                return embeddings

            except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt <= 3:
                    sleep = _retry_sleeps[attempt - 1]
                    logger.warning(
                        f"Embed retry {attempt}/3 after {sleep}s"
                        f" — {type(exc).__name__}: {exc}"
                    )
                    await asyncio.sleep(sleep)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 or exc.response.status_code == 429:
                    last_exc = exc
                    if attempt <= 3:
                        sleep = _retry_sleeps[attempt - 1]
                        logger.warning(
                            f"Embed retry {attempt}/3 after {sleep}s"
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
            await self._call_embed(["health check"])
            return True
        except Exception as e:
            logger.warning(f"Embedding health check failed: {e}")
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
