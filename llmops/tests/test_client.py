import importlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, "client")

RECEIVED: list = []
_SLOW_HANDLER = False


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if _SLOW_HANDLER:
            time.sleep(0.3)  # Delay to prevent worker draining while enqueuing
        body = self.rfile.read(int(self.headers["Content-Length"]))
        RECEIVED.append({"path": self.path,
                         "auth": self.headers.get("Authorization"),
                         "body": json.loads(body)})
        self.send_response(202)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def collector():
    """Prawdziwy serwer HTTP, nie mock — testujemy sciezke sieciowa klienta."""
    global _SLOW_HANDLER
    _SLOW_HANDLER = False
    RECEIVED.clear()
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", RECEIVED
    srv.shutdown()


@pytest.fixture
def slow_collector():
    """Serwer HTTP z sztucznym opoznieniem aby uniemozliwic pracu drenowania."""
    global _SLOW_HANDLER
    _SLOW_HANDLER = True
    RECEIVED.clear()
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", RECEIVED
    _SLOW_HANDLER = False
    srv.shutdown()


def _fresh_client(monkeypatch, url: str):
    monkeypatch.setenv("LLMOPS_URL", url)
    monkeypatch.setenv("LLMOPS_TOKEN", "t0k")
    monkeypatch.setenv("LLMOPS_PROJECT", "argus")
    monkeypatch.setenv("LLMOPS_SERVICE", "collector")
    monkeypatch.setenv("LLMOPS_ENV", "test")
    monkeypatch.setenv("LLMOPS_HOST", "local")
    import llmops_client
    return importlib.reload(llmops_client)


def test_record_reaches_collector(monkeypatch, collector):
    url, received = collector
    c = _fresh_client(monkeypatch, url)
    c.record(provider="gemini", model="gemini-flash-latest", call_type="generate",
             tokens_in=5, tokens_out=7, latency_ms=120, ok=True)
    c.flush()
    assert len(received) == 1
    assert received[0]["path"] == "/v1/calls/batch"
    assert received[0]["auth"] == "Bearer t0k"
    row = received[0]["body"][0]
    assert row["project"] == "argus"
    assert row["service"] == "collector"
    assert row["provider"] == "gemini"
    assert row["tokens_in"] == 5


def test_no_url_is_noop(monkeypatch):
    monkeypatch.setenv("LLMOPS_URL", "")
    import llmops_client
    c = importlib.reload(llmops_client)
    c.record(provider="x", model="y", call_type="generate")
    c.flush()


def test_collector_down_does_not_raise(monkeypatch):
    c = _fresh_client(monkeypatch, "http://127.0.0.1:1")
    c.record(provider="x", model="y", call_type="generate")
    c.flush(timeout=3)


def test_full_queue_drops_without_raising(monkeypatch, slow_collector):
    url, _ = slow_collector
    monkeypatch.setenv("LLMOPS_QUEUE_MAX", "2")
    c = _fresh_client(monkeypatch, url)
    for _ in range(300):
        c.record(provider="x", model="y", call_type="generate")
    c.flush(timeout=10)
    # Verify the drop path was exercised: _dropped > 0 proves queue.Full was caught
    assert c._dropped > 0, "Expected queue to overflow and drop records"


def test_batches_multiple_records(monkeypatch, collector):
    url, received = collector
    c = _fresh_client(monkeypatch, url)
    for i in range(20):
        c.record(provider="x", model=f"m{i}", call_type="generate")
    c.flush(timeout=5)
    total = sum(len(r["body"]) for r in received)
    assert total == 20
