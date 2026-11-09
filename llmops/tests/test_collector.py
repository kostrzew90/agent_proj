import os
import httpx
import pytest

BASE = os.getenv("LLMOPS_TEST_URL", "http://127.0.0.1:8091")
TOKEN = os.getenv("LLMOPS_TOKEN", "changeme-shared-bearer-token")
AUTH = {"Authorization": f"Bearer {TOKEN}"}

VALID = {
    "project": "rag", "service": "chat-api", "environment": "test",
    "host": "local", "provider": "openrouter", "model": "openai/gpt-4o-mini",
    "call_type": "generate", "tokens_in": 10, "tokens_out": 20,
    "latency_ms": 150, "ok": True,
}


def test_health_ok():
    r = httpx.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_valid_call_is_stored(db):
    r = httpx.post(f"{BASE}/v1/calls", json=VALID, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT project, model, tokens_in, ok FROM llm_calls")
        assert cur.fetchall() == [("rag", "openai/gpt-4o-mini", 10, True)]


def test_missing_token_rejected():
    r = httpx.post(f"{BASE}/v1/calls", json=VALID, timeout=5)
    assert r.status_code == 401


def test_payload_with_prompt_rejected(db):
    bad = dict(VALID, prompt="tajna tresc uzytkownika")
    r = httpx.post(f"{BASE}/v1/calls", json=bad, headers=AUTH, timeout=5)
    assert r.status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM llm_calls")
        assert cur.fetchone()[0] == 0


def test_api_key_in_error_is_redacted(db):
    payload = dict(VALID, ok=False, error="401 from provider, key sk-abcdef1234567890 rejected")
    r = httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT error FROM llm_calls")
        stored = cur.fetchone()[0]
    assert "sk-abcdef1234567890" not in stored
    assert "[REDACTED]" in stored


def test_stripe_key_in_error_is_redacted(db):
    payload = dict(VALID, ok=False,
                    error="stripe charge failed, key sk_live_51H8xyzABCDEFGHIJKLMNOP rejected")
    r = httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT error FROM llm_calls")
        stored = cur.fetchone()[0]
    assert "sk_live_51H8xyzABCDEFGHIJKLMNOP" not in stored
    assert "[REDACTED]" in stored
    assert "stripe charge failed" in stored


def test_aws_key_in_error_is_redacted(db):
    payload = dict(VALID, ok=False,
                    error="upload failed, AWS key AKIAIOSFODNN7EXAMPLE denied")
    r = httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT error FROM llm_calls")
        stored = cur.fetchone()[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in stored
    assert "[REDACTED]" in stored
    assert "upload failed" in stored


def test_connection_string_password_is_redacted(db):
    payload = dict(VALID, ok=False,
                    error="connection failed: postgres://dbuser:hunter2pass@db.internal:5432/mydb timeout")
    r = httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT error FROM llm_calls")
        stored = cur.fetchone()[0]
    assert "hunter2pass" not in stored
    assert "[REDACTED]" in stored
    assert "db.internal" in stored


def test_long_error_is_truncated(db):
    payload = dict(VALID, ok=False, error="x" * 5000)
    httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    with db.cursor() as cur:
        cur.execute("SELECT length(error) FROM llm_calls")
        assert cur.fetchone()[0] == 300


def test_batch_is_stored(db):
    r = httpx.post(f"{BASE}/v1/calls/batch", json=[VALID, VALID, VALID],
                   headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM llm_calls")
        assert cur.fetchone()[0] == 3


def test_oversized_batch_rejected():
    r = httpx.post(f"{BASE}/v1/calls/batch", json=[VALID] * 101, headers=AUTH, timeout=5)
    assert r.status_code == 413
