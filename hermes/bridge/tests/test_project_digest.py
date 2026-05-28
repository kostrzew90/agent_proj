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


class TestGitLog:
    def test_parses_commits_and_shortstat(self):
        stdout = (
            "abc1234 feat(rag): wire reranker\n"
            " 2 files changed, 30 insertions(+), 5 deletions(-)\n"
            "def5678 fix(rag): close http clients\n"
            " 1 file changed, 4 insertions(+)\n"
        )
        out = hermes_bridge._pd_parse_git_log(stdout)
        assert len(out["commits"]) == 2
        assert "feat(rag): wire reranker" in out["commits"][0]
        assert out["files_changed"] == 3

    def test_handles_empty_output(self):
        out = hermes_bridge._pd_parse_git_log("")
        assert out == {"commits": [], "files_changed": 0}

    def test_tolerates_merge_commit_lines(self):
        stdout = (
            "abc1234 Merge branch 'feature'\n"
            "Binary files differ\n"
            " 1 file changed, 0 insertions(+), 0 deletions(-)\n"
        )
        out = hermes_bridge._pd_parse_git_log(stdout)
        assert len(out["commits"]) == 1
        assert out["files_changed"] == 1

    def test_git_log_since_missing_repo(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hermes_bridge, "_PD_PROJECTS", {"fake": str(tmp_path / "no-such-dir")})
        out = hermes_bridge._pd_git_log_since(hours=12)
        assert out["fake"] == {"error": "repo missing"}

    def test_git_log_since_rejects_non_int(self):
        with pytest.raises(AssertionError):
            hermes_bridge._pd_git_log_since(hours="12")  # type: ignore


class TestHealthCheck:
    def test_parses_docker_ps_states(self, monkeypatch):
        fake_stdout = (
            "rag-backend\tUp 2 hours\n"
            "rag-postgres\tUp 2 hours\n"
            "hermes-watcher\tExited (1) 30 minutes ago\n"
            "old-container\tRestarting (3) 5 seconds ago\n"
        )

        class FakeCompleted:
            returncode = 0
            stdout = fake_stdout

        def fake_run(*args, **kwargs):
            return FakeCompleted()

        monkeypatch.setattr(hermes_bridge.subprocess, "run", fake_run)
        monkeypatch.setattr(hermes_bridge, "_PD_HTTP_ENDPOINTS", {})

        out = hermes_bridge._pd_health_check()
        assert out["containers"]["rag-backend"] == "up"
        assert out["containers"]["hermes-watcher"] == "exited"
        assert out["containers"]["old-container"] == "restarting"

    def test_docker_failure_does_not_crash(self, monkeypatch):
        import subprocess as _subprocess

        def fake_run(*args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd="docker", timeout=5)

        monkeypatch.setattr(hermes_bridge.subprocess, "run", fake_run)
        monkeypatch.setattr(hermes_bridge, "_PD_HTTP_ENDPOINTS", {})

        out = hermes_bridge._pd_health_check()
        assert "containers" in out
        assert "http" in out


class TestScanExtras:
    def test_picks_up_recent_log(self, tmp_path):
        (tmp_path / "newthing.log").write_text("event A\nevent B\n", encoding="utf-8")
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        names = [e["file"] for e in out]
        assert "newthing.log" in names
        target = next(e for e in out if e["file"] == "newthing.log")
        assert "event B" in target["last"]

    def test_skips_denylisted(self, tmp_path):
        (tmp_path / "auth.log").write_text("password=secret123\n", encoding="utf-8")
        (tmp_path / "secrets.json").write_text("{}\n", encoding="utf-8")
        (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
        (tmp_path / "cdp.log").write_text("cookie\n", encoding="utf-8")
        (tmp_path / "llm-proxy.jsonl").write_text('{"prompt":"x"}\n', encoding="utf-8")
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        files = {e["file"] for e in out}
        assert "auth.log" not in files
        assert "secrets.json" not in files
        assert ".env" not in files
        assert "cdp.log" not in files
        assert "llm-proxy.jsonl" not in files

    def test_only_allowlist_extensions(self, tmp_path):
        (tmp_path / "ok.log").write_text("entry\n", encoding="utf-8")
        (tmp_path / "binary.bin").write_text("xxx\n", encoding="utf-8")
        (tmp_path / "image.png").write_text("yyy\n", encoding="utf-8")
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        files = {e["file"] for e in out}
        assert "ok.log" in files
        assert "binary.bin" not in files
        assert "image.png" not in files

    def test_skips_old_files(self, tmp_path):
        import os as _os
        old = tmp_path / "old.log"
        old.write_text("old entry\n", encoding="utf-8")
        old_mtime = time.time() - 48 * 3600
        _os.utime(old, (old_mtime, old_mtime))
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        assert "old.log" not in {e["file"] for e in out}

    def test_jsonl_pretty_extract(self, tmp_path):
        (tmp_path / "thing.jsonl").write_text(
            '{"event":"crawl_done","count":47}\n',
            encoding="utf-8",
        )
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        target = next(e for e in out if e["file"] == "thing.jsonl")
        assert "event=crawl_done" in target["last"] or "crawl_done" in target["last"]

    def test_caps_at_ten_extras(self, tmp_path):
        for i in range(15):
            (tmp_path / f"x{i}.log").write_text(f"entry {i}\n", encoding="utf-8")
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        assert len(out) <= 10

    def test_truncates_long_line(self, tmp_path):
        (tmp_path / "verbose.log").write_text("X" * 1000 + "\n", encoding="utf-8")
        out = hermes_bridge._pd_scan_extras(since_hours=24)
        target = next(e for e in out if e["file"] == "verbose.log")
        assert len(target["last"]) <= 180


class TestDigestLock:
    def test_first_acquire_succeeds(self, tmp_path):
        with hermes_bridge._pd_digest_lock("morning") as acquired:
            assert acquired is True
        assert not (tmp_path / ".digest-morning.lock").exists()

    def test_double_acquire_blocked(self, tmp_path):
        with hermes_bridge._pd_digest_lock("evening") as first:
            assert first is True
            with hermes_bridge._pd_digest_lock("evening") as second:
                assert second is False

    def test_stale_lock_reclaimed(self, tmp_path):
        lock_path = tmp_path / ".digest-morning.lock"
        lock_path.write_text("999999")
        with hermes_bridge._pd_digest_lock("morning") as acquired:
            assert acquired is True

    def test_concurrent_keys_independent(self, tmp_path):
        with hermes_bridge._pd_digest_lock("morning") as a:
            with hermes_bridge._pd_digest_lock("evening") as b:
                assert a is True
                assert b is True
