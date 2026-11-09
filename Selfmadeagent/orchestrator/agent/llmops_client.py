"""Klient telemetrii LLMOps — kolejka w pamieci + watek roboczy.

KANONICZNE ZRODLO: llmops/client/llmops_client.py
Kopie w innych projektach sa generowane przez llmops/client/sync_clients.py.
Nie edytuj kopii — edytuj oryginal i uruchom sync.

Zasada: telemetria nigdy nie wywraca ani nie spowalnia wywolania LLM.
Kolejka pelna -> gubimy metryke. Kolektor lezy -> gubimy metryke. Nigdy wyjatek.
"""
import atexit
import json
import logging
import os
import queue
import threading
import urllib.request

logger = logging.getLogger("llmops")

_URL = os.getenv("LLMOPS_URL", "").rstrip("/")
_TOKEN = os.getenv("LLMOPS_TOKEN", "")
_DIMS = {
    "project": os.getenv("LLMOPS_PROJECT", "unknown"),
    "service": os.getenv("LLMOPS_SERVICE", "unknown"),
    "environment": os.getenv("LLMOPS_ENV", "unknown"),
    "host": os.getenv("LLMOPS_HOST", "unknown"),
}

_QUEUE_MAX = int(os.getenv("LLMOPS_QUEUE_MAX", "1000"))
_BATCH_MAX = 100
_TIMEOUT = float(os.getenv("LLMOPS_TIMEOUT", "2.0"))

_q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_dropped = 0


def _post(payload: list[dict]) -> None:
    req = urllib.request.Request(
        f"{_URL}/v1/calls/batch",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT):
        pass


def _drain() -> None:
    while True:
        item = _q.get()
        batch = [item]
        while len(batch) < _BATCH_MAX:
            try:
                batch.append(_q.get_nowait())
            except queue.Empty:
                break
        try:
            _post(batch)
        except Exception as exc:
            logger.warning("llmops: %d metryk utraconych: %s", len(batch), exc)
        finally:
            for _ in batch:
                _q.task_done()


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, name="llmops", daemon=True)
            _worker.start()


def record(provider: str, model: str, call_type: str, tokens_in: int = 0,
           tokens_out: int = 0, latency_ms: int | None = None, ok: bool = True,
           error: str | None = None, cost_usd: float | None = None,
           tokens_estimated: bool = False, trace_id: str | None = None) -> None:
    """Zapisz metadane jednego wywolania LLM. Nigdy nie podnosi wyjatku."""
    global _dropped
    if not _URL:
        return
    try:
        _ensure_worker()
        _q.put_nowait({
            **_DIMS,
            "provider": provider, "model": model, "call_type": call_type,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_estimated": tokens_estimated, "cost_usd": cost_usd,
            "latency_ms": latency_ms, "ok": ok,
            "error": error, "trace_id": trace_id,
        })
    except queue.Full:
        _dropped += 1
        if _dropped % 100 == 1:
            logger.warning("llmops: kolejka pelna, %d metryk odrzuconych", _dropped)
    except Exception as exc:
        logger.warning("llmops: record nieudany: %s", exc)


def flush(timeout: float = 5.0) -> None:
    """Poczekaj na oproznienie kolejki. Do testow i zamykania procesu."""
    if not _URL:
        return
    done = threading.Event()
    threading.Thread(target=lambda: (_q.join(), done.set()), daemon=True).start()
    done.wait(timeout)


atexit.register(flush)
