"""Unit tests for project-digest skill."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hermes_bridge


@pytest.fixture(autouse=True)
def _patch_audit_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(hermes_bridge, "_AUDIT_DIR", tmp_path)
    hermes_bridge._ensure_dirs()


class TestSanitizer:
    def test_redacts_openai_key(self):
        text = "Using sk-proj-abc123def456ghi789jkl012mno345pqr in request"
        out = hermes_bridge._pd_sanitize(text)
        assert "sk-proj-abc123" not in out
        assert "***REDACTED***" in out

    def test_redacts_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        out = hermes_bridge._pd_sanitize(text)
        assert "eyJhbGci" not in out
        assert "***REDACTED***" in out or "***JWT-REDACTED***" in out

    def test_redacts_api_key_assignment(self):
        text = "config: api_key=secret123, token=abc, OPENAI_API_KEY"
        out = hermes_bridge._pd_sanitize(text)
        assert "secret123" not in out
        assert "***REDACTED***" in out

    def test_redacts_long_hex(self):
        text = "hash: " + "a" * 40 + " end"
        out = hermes_bridge._pd_sanitize(text)
        assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in out
        assert "***HEX-REDACTED***" in out

    def test_preserves_normal_text(self):
        text = "Normal commit message: feat(rag): add reranker"
        out = hermes_bridge._pd_sanitize(text)
        assert out == text
