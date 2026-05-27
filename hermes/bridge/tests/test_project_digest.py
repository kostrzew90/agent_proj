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


class TestParseCosts:
    def _write_costs(self, tmp_path, entries):
        path = tmp_path / "costs.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    def test_aggregates_by_model(self, tmp_path):
        now = time.time()
        self._write_costs(tmp_path, [
            {"timestamp": now - 1000, "model": "gpt-5", "cost_usd": 0.50},
            {"timestamp": now - 2000, "model": "gpt-5", "cost_usd": 0.25},
            {"timestamp": now - 500, "model": "claude-sonnet", "cost_usd": 0.10},
        ])
        out = hermes_bridge._pd_parse_costs(since_hours=1)
        assert out["entries"] == 3
        assert out["total_usd"] == pytest.approx(0.85)
        assert out["by_model"]["gpt-5"] == pytest.approx(0.75)
        assert out["by_model"]["claude-sonnet"] == pytest.approx(0.10)

    def test_ignores_entries_outside_window(self, tmp_path):
        now = time.time()
        self._write_costs(tmp_path, [
            {"timestamp": now - 100, "model": "a", "cost_usd": 1.0},
            {"timestamp": now - 7200, "model": "b", "cost_usd": 99.0},
        ])
        out = hermes_bridge._pd_parse_costs(since_hours=1)
        assert out["entries"] == 1
        assert out["total_usd"] == pytest.approx(1.0)

    def test_handles_malformed_jsonl(self, tmp_path):
        path = tmp_path / "costs.jsonl"
        now = time.time()
        path.write_text(
            f'{{"timestamp": {now - 100}, "model": "ok", "cost_usd": 0.5}}\n'
            'NOT JSON\n'
            '{"incomplete":\n'
            f'{{"timestamp": {now - 50}, "model": "ok2", "cost_usd": 0.3}}\n',
            encoding="utf-8",
        )
        out = hermes_bridge._pd_parse_costs(since_hours=1)
        assert out["entries"] == 2
        assert out["total_usd"] == pytest.approx(0.8)

    def test_handles_missing_file(self, tmp_path):
        out = hermes_bridge._pd_parse_costs(since_hours=1)
        assert out == {"total_usd": 0.0, "by_model": {}, "entries": 0}

    def test_caps_oversize_lines(self, tmp_path):
        path = tmp_path / "costs.jsonl"
        now = time.time()
        oversize = '{"timestamp": ' + str(now - 50) + ', "model": "x", "padding": "' + ("z" * 20000) + '"}'
        path.write_text(
            oversize + "\n" +
            f'{{"timestamp": {now - 30}, "model": "good", "cost_usd": 0.1}}\n',
            encoding="utf-8",
        )
        out = hermes_bridge._pd_parse_costs(since_hours=1)
        assert out["entries"] == 1
        assert out["total_usd"] == pytest.approx(0.1)
