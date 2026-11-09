# Project Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Twice-daily Telegram digest (morning 8:00 UTC, evening 20:00 UTC) summarising LLM costs, git activity, service health, review-learn highlights, and extras audit logs across all local AI stack projects.

**Architecture:** Single handler `_handle_project_digest(skill_name)` dispatched by two `_CRONS` entries (mode wyciągany ze skill_name, nie z `datetime.now().hour`). Wszystkie helpery (`_pd_*` prefix dla namespace) izolowane jako pure functions — testowalne bez monkeypatch poza `_AUDIT_DIR`. Sanitizer + lockfile + size caps zaimplementowane jako MUST HAVE security/reliability boundary.

**Tech Stack:** Python 3.11+, pytest, subprocess (git/docker), httpx (HTTP health), stdlib `re`/`json`/`collections.deque`.

**Spec:** `docs/superpowers/specs/2026-05-27-project-digest-design.md`

---

## File Structure

| Plik | Akcja | Odpowiedzialność |
|------|-------|------------------|
| `hermes/bridge/hermes_bridge.py` | Modify | +`_CRONS` wpisy (linia ~146), +`_pd_*` helpers, +`_handle_project_digest()`, +routing w `_dispatch_cron_skill` i `_dispatch_skill_text` |
| `hermes/skills/project-digest.md` | Create | Dokumentacja skilla (When to use / Steps / Watch out for) |
| `hermes/bridge/tests/test_project_digest.py` | Create | Unit tests dla helperów + handler + sanitizer + lockfile |

Wszystkie helpery prefixowane `_pd_` żeby uniknąć kolizji z istniejącym kodem (`_handle_*`, `_cron_*` istnieją).

---

## Task 1: Sanitizer (security boundary)

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py` (dodać po istniejącej sekcji helperów, koło linii 2660 przed `_cron_send_to_telegram`)
- Test: `hermes/bridge/tests/test_project_digest.py` (nowy plik)

- [ ] **Step 1: Write the failing test**

Plik `hermes/bridge/tests/test_project_digest.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestSanitizer -v
```

Expected: FAIL — `AttributeError: module 'hermes_bridge' has no attribute '_pd_sanitize'`.

- [ ] **Step 3: Write minimal implementation**

W `hermes/bridge/hermes_bridge.py` dodać `import re` jeśli brak (sprawdzić linie 11-25), potem dodać sekcję przed `_cron_send_to_telegram` (~linia 2660):

```python
# ---------------------------------------------------------------------------
# Project Digest (skill) — helpers prefixed _pd_*
# ---------------------------------------------------------------------------

import re as _re_pd

_PD_SECRET_PATTERNS: list[tuple] = [
    (_re_pd.compile(r"sk-[A-Za-z0-9_-]{16,}"), "sk-***REDACTED***"),
    (_re_pd.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", _re_pd.IGNORECASE), "Bearer ***REDACTED***"),
    (_re_pd.compile(r"(api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]+", _re_pd.IGNORECASE), r"\1=***REDACTED***"),
    (_re_pd.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "***JWT-REDACTED***"),
    (_re_pd.compile(r"\b[a-f0-9]{40,}\b"), "***HEX-REDACTED***"),
    (_re_pd.compile(r"\b(OPENAI_API_KEY|ANTHROPIC_API_KEY|GROQ_API_KEY|TELEGRAM_BOT_TOKEN)\b"), "***ENV-VAR***"),
]


def _pd_sanitize(text: str) -> str:
    """Mask secrets in any string before sending to Telegram (external boundary)."""
    for pat, repl in _PD_SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text
```

(`re` może już być importowany — sprawdź; jeśli tak, użyj `re` zamiast `_re_pd`.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestSanitizer -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_sanitize for secret masking in project-digest"
```

---

## Task 2: Cost parser z guardrails

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py` (po `_pd_sanitize`)
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

Dopisać do `test_project_digest.py`:

```python
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
            {"timestamp": now - 7200, "model": "b", "cost_usd": 99.0},  # 2h ago
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
        # No costs.jsonl created
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
        # Oversize line skipped, only second counted
        assert out["entries"] == 1
        assert out["total_usd"] == pytest.approx(0.1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestParseCosts -v
```

Expected: FAIL — `_pd_parse_costs` not defined.

- [ ] **Step 3: Write minimal implementation**

Dodać po `_pd_sanitize`:

```python
import collections as _collections_pd


def _pd_to_epoch(ts) -> float:
    """Convert ISO string or numeric timestamp to epoch seconds. 0.0 on failure."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _pd_parse_costs(since_hours: int) -> dict:
    """Aggregate costs.jsonl entries newer than cutoff. Robust to malformed lines."""
    assert isinstance(since_hours, int), "since_hours must be int"
    cutoff = time.time() - since_hours * 3600
    by_model: dict[str, float] = {}
    total = 0.0
    entries = 0

    path = _AUDIT_DIR / "costs.jsonl"
    if not path.exists():
        return {"total_usd": 0.0, "by_model": {}, "entries": 0}

    MAX_LINE = 16384
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = _collections_pd.deque(f, maxlen=5000)
    except OSError:
        return {"total_usd": 0.0, "by_model": {}, "entries": 0}

    for line in lines:
        if len(line) > MAX_LINE:
            continue
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(e, dict):
            continue
        ts = _pd_to_epoch(e.get("timestamp") or e.get("ts") or 0)
        if ts < cutoff:
            continue
        model = str(e.get("model", "unknown"))
        try:
            cost = float(e.get("cost_usd", 0) or 0)
        except (TypeError, ValueError):
            cost = 0.0
        by_model[model] = by_model.get(model, 0.0) + cost
        total += cost
        entries += 1

    return {"total_usd": total, "by_model": by_model, "entries": entries}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestParseCosts -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_parse_costs with malformed-line + size-cap guards"
```

---

## Task 3: Git log helper

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

Dopisać do `test_project_digest.py`:

```python
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
        # Merge commits or binary files may produce odd lines — must not crash
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestGitLog -v
```

Expected: FAIL — helpers not defined.

- [ ] **Step 3: Write minimal implementation**

Dodać:

```python
import subprocess as _subprocess_pd

_PD_PROJECTS: dict[str, str] = {
    "RAG": "/workspace/ro/RAG",
    "Selfmadeagent": "/workspace/ro/Selfmadeagent",
    "VINhunter": "/workspace/ro/VIN OSINT/vinhunter",
    "trading-app": "/workspace/ro/trading-app",
    "hermes": "/workspace/ro/hermes",
}


def _pd_parse_git_log(stdout: str) -> dict:
    """Best-effort parser for `git log --pretty=format:%h %s --shortstat`."""
    commits: list[str] = []
    files_changed = 0
    for line in stdout.splitlines():
        try:
            if _re_pd.match(r"^[a-f0-9]{7,40}\s", line):
                commits.append(line)
            elif " file" in line and "changed" in line:
                m = _re_pd.search(r"(\d+)\s+files?\s+changed", line)
                if m:
                    files_changed += int(m.group(1))
        except Exception:
            continue
    return {"commits": commits, "files_changed": files_changed}


def _pd_git_log_since(hours: int) -> dict:
    """Run `git log --since=<hours> hours ago` per project. Soft-fail on missing/broken repos."""
    assert isinstance(hours, int), "hours must be int (subprocess safety)"
    out: dict[str, dict] = {}
    for name, path in _PD_PROJECTS.items():
        repo = Path(path)
        if not repo.exists() or not (repo / ".git").exists():
            out[name] = {"error": "repo missing"}
            continue
        try:
            r = _subprocess_pd.run(
                ["git", "log", f"--since={hours} hours ago",
                 "--pretty=format:%h %s", "--shortstat"],
                cwd=str(repo), timeout=10, capture_output=True, text=True,
            )
            if r.returncode != 0:
                out[name] = {"error": f"git rc={r.returncode}"}
                continue
            out[name] = _pd_parse_git_log(r.stdout)
        except _subprocess_pd.TimeoutExpired:
            out[name] = {"error": "timeout"}
        except Exception as exc:
            out[name] = {"error": str(exc)[:60]}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestGitLog -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_git_log_since + best-effort shortstat parser"
```

---

## Task 4: Health check (docker + HTTP)

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

```python
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

        monkeypatch.setattr(hermes_bridge._subprocess_pd, "run", fake_run)
        # Disable HTTP probing for this test
        monkeypatch.setattr(hermes_bridge, "_PD_HTTP_ENDPOINTS", {})

        out = hermes_bridge._pd_health_check()
        assert out["containers"]["rag-backend"] == "up"
        assert out["containers"]["hermes-watcher"] == "exited"
        assert out["containers"]["old-container"] == "restarting"

    def test_docker_failure_does_not_crash(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise _subprocess_pd.TimeoutExpired(cmd="docker", timeout=5)

        import subprocess as _subprocess_pd  # noqa
        monkeypatch.setattr(hermes_bridge._subprocess_pd, "run", fake_run)
        monkeypatch.setattr(hermes_bridge, "_PD_HTTP_ENDPOINTS", {})

        out = hermes_bridge._pd_health_check()
        assert "containers" in out
        assert "http" in out  # no crash
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestHealthCheck -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Dodać:

```python
_PD_HTTP_ENDPOINTS: dict[str, str] = {
    "RAG": "http://rag-backend:8000/health",
    "Selfmadeagent": "http://selfmadeagent:8080/health",
}


def _pd_health_check() -> dict:
    """Return container states (docker ps -a) + HTTP /health pings."""
    containers: dict[str, str] = {}
    try:
        r = _subprocess_pd.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            timeout=5, capture_output=True, text=True,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                name, _, status = line.partition("\t")
                if not name:
                    continue
                if status.startswith("Up"):
                    containers[name] = "up"
                elif status.startswith("Exited"):
                    containers[name] = "exited"
                elif status.startswith("Restarting"):
                    containers[name] = "restarting"
                else:
                    containers[name] = "unknown"
    except Exception as exc:
        containers["_error"] = str(exc)[:60]

    http: dict[str, dict] = {}
    for name, url in _PD_HTTP_ENDPOINTS.items():
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url)
            http[name] = {
                "ok": resp.status_code == 200,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as exc:
            http[name] = {"ok": False, "error": str(exc)[:40]}

    return {"containers": containers, "http": http}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestHealthCheck -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_health_check (docker ps -a + HTTP probes)"
```

---

## Task 5: Extras scanner (allowlist + denylist)

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

```python
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
        old = tmp_path / "old.log"
        old.write_text("old entry\n", encoding="utf-8")
        # Set mtime to 48h ago
        old_mtime = time.time() - 48 * 3600
        import os
        os.utime(old, (old_mtime, old_mtime))
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestScanExtras -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
_PD_ALLOW_PATTERNS: tuple = ("*.log", "*.jsonl")
_PD_DENY_FILES: set = {
    "auth.log", "secrets.json", ".env",
    "cdp.log", "cdp_readonly.log",
    "costs.jsonl", "review-learn.log", "cron.log",
    "research.log", "watcher-heartbeat.txt",
    "llm-proxy.jsonl",
    "self-learn.log",
}


def _pd_scan_extras(since_hours: int) -> list[dict]:
    """Scan /audit for recent log/jsonl files not handled elsewhere."""
    assert isinstance(since_hours, int)
    cutoff = time.time() - since_hours * 3600
    extras: list[dict] = []
    MAX_LINE = 16384

    candidates: set = set()
    for pat in _PD_ALLOW_PATTERNS:
        candidates.update(_AUDIT_DIR.glob(pat))

    for path in sorted(candidates):
        if path.name in _PD_DENY_FILES or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                tail = _collections_pd.deque(f, maxlen=1)
        except OSError:
            continue
        if not tail:
            continue
        line = tail[-1].strip()
        if len(line) > MAX_LINE:
            continue

        display = line[:180]
        if path.suffix == ".jsonl":
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    for key in ("message", "event", "type", "msg", "summary"):
                        if key in obj:
                            display = f"{key}={obj[key]}"[:180]
                            break
            except (json.JSONDecodeError, ValueError):
                pass

        extras.append({"file": path.name, "last": display})
        if len(extras) >= 10:
            break

    return extras
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestScanExtras -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_scan_extras with allowlist + denylist"
```

---

## Task 6: Lockfile z atomic reclaim

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

```python
class TestDigestLock:
    def test_first_acquire_succeeds(self, tmp_path):
        with hermes_bridge._pd_digest_lock("morning") as acquired:
            assert acquired is True
        # Lock file cleaned up
        assert not (tmp_path / ".digest-morning.lock").exists()

    def test_double_acquire_blocked(self, tmp_path):
        with hermes_bridge._pd_digest_lock("evening") as first:
            assert first is True
            with hermes_bridge._pd_digest_lock("evening") as second:
                assert second is False

    def test_stale_lock_reclaimed(self, tmp_path):
        lock_path = tmp_path / ".digest-morning.lock"
        # Write a PID that definitely doesn't exist
        lock_path.write_text("999999")
        with hermes_bridge._pd_digest_lock("morning") as acquired:
            assert acquired is True

    def test_concurrent_keys_independent(self, tmp_path):
        with hermes_bridge._pd_digest_lock("morning") as a:
            with hermes_bridge._pd_digest_lock("evening") as b:
                assert a is True
                assert b is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestDigestLock -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
import contextlib as _contextlib_pd


@_contextlib_pd.contextmanager
def _pd_digest_lock(name: str):
    """Singleton execution lock with atomic stale-reclaim. Yields bool (acquired)."""
    lock_path = _AUDIT_DIR / f".digest-{name}.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    def _acquire() -> int | None:
        try:
            fd = os.open(str(lock_path), flags, 0o600)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            return None

    fd = _acquire()
    if fd is None:
        try:
            stale_pid = int(lock_path.read_text().strip())
            os.kill(stale_pid, 0)  # raises if dead
            yield False
            return
        except (ProcessLookupError, ValueError, PermissionError, FileNotFoundError):
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            fd = _acquire()
            if fd is None:
                yield False
                return

    try:
        yield True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestDigestLock -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_digest_lock with atomic stale-reclaim + O_NOFOLLOW"
```

---

## Task 7: Review-learn queue + highlights + research helpers

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

```python
class TestReviewLearnQueue:
    def test_counts_new_last_24h(self, tmp_path):
        log = tmp_path / "review-learn.log"
        now = time.time()
        log.write_text(
            json.dumps({"timestamp": now - 1000, "file": "a.py"}) + "\n" +
            json.dumps({"timestamp": now - 100, "file": "b.py"}) + "\n" +
            json.dumps({"timestamp": now - 200000, "file": "c.py"}) + "\n",
            encoding="utf-8",
        )
        out = hermes_bridge._pd_review_learn_queue()
        assert out["new_last_24h"] == 2

    def test_missing_log_returns_zero(self, tmp_path):
        out = hermes_bridge._pd_review_learn_queue()
        assert out["new_last_24h"] == 0


class TestReviewLearnHighlights:
    def test_extracts_recent_previews(self, tmp_path):
        log = tmp_path / "review-learn.log"
        now = time.time()
        log.write_text(
            json.dumps({"timestamp": now - 3000, "file": "old.py", "preview": "old finding"}) + "\n" +
            json.dumps({"timestamp": now - 1000, "file": "x.py", "preview": "• resource leak"}) + "\n" +
            json.dumps({"timestamp": now - 500, "file": "y.py", "preview": "• hidden invariant"}) + "\n",
            encoding="utf-8",
        )
        out = hermes_bridge._pd_review_learn_highlights(last_n=2)
        assert len(out) == 2
        # Most recent two
        files = [h["file"] for h in out]
        assert "y.py" in files
        assert "x.py" in files


class TestResearchLog:
    def test_counts_entries_in_window(self, tmp_path):
        log = tmp_path / "research.log"
        now = time.time()
        log.write_text(
            json.dumps({"timestamp": now - 1000, "topic": "agentic patterns"}) + "\n" +
            json.dumps({"timestamp": now - 500, "topic": "hybrid RRF"}) + "\n" +
            json.dumps({"timestamp": now - 50000, "topic": "old"}) + "\n",
            encoding="utf-8",
        )
        out = hermes_bridge._pd_research_log_since(hours=12)
        assert out["count"] == 2
        assert "hybrid RRF" in out["last_topic"] or "agentic" in out["last_topic"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestReviewLearnQueue tests/test_project_digest.py::TestReviewLearnHighlights tests/test_project_digest.py::TestResearchLog -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _pd_iter_jsonl_recent(path: Path, since_hours: int) -> list[dict]:
    """Read JSONL, yield parsed dicts within window. Robust to malformed lines."""
    if not path.exists():
        return []
    cutoff = time.time() - since_hours * 3600
    entries: list[dict] = []
    MAX_LINE = 16384
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = _collections_pd.deque(f, maxlen=5000)
    except OSError:
        return []
    for line in lines:
        if len(line) > MAX_LINE:
            continue
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(e, dict):
            continue
        ts = _pd_to_epoch(e.get("timestamp") or e.get("ts") or 0)
        if ts < cutoff:
            continue
        entries.append(e)
    return entries


def _pd_review_learn_queue() -> dict:
    """Stats: how many reviews in last 24h."""
    log_path = _AUDIT_DIR / "review-learn.log"
    entries = _pd_iter_jsonl_recent(log_path, since_hours=24)
    return {"new_last_24h": len(entries)}


def _pd_review_learn_highlights(last_n: int = 2) -> list[dict]:
    """Return last N entries with file + preview."""
    log_path = _AUDIT_DIR / "review-learn.log"
    entries = _pd_iter_jsonl_recent(log_path, since_hours=24)
    entries.sort(
        key=lambda e: _pd_to_epoch(e.get("timestamp") or e.get("ts") or 0),
        reverse=True,
    )
    out: list[dict] = []
    for e in entries[:last_n]:
        out.append({
            "file": str(e.get("file", "?"))[:60],
            "preview": str(e.get("preview", ""))[:80],
        })
    return out


def _pd_research_log_since(hours: int) -> dict:
    """Count research.log entries in window + last topic."""
    log_path = _AUDIT_DIR / "research.log"
    entries = _pd_iter_jsonl_recent(log_path, since_hours=hours)
    if not entries:
        return {"count": 0, "last_topic": ""}
    entries.sort(
        key=lambda e: _pd_to_epoch(e.get("timestamp") or e.get("ts") or 0),
        reverse=True,
    )
    last = entries[0].get("topic") or entries[0].get("query") or entries[0].get("question") or ""
    return {"count": len(entries), "last_topic": str(last)[:100]}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py -k "ReviewLearnQueue or ReviewLearnHighlights or ResearchLog" -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add review-learn queue/highlights + research log helpers"
```

---

## Task 8: Formatter + main handler

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py`
- Test: `hermes/bridge/tests/test_project_digest.py`

- [ ] **Step 1: Write the failing test**

```python
class TestFormatDigest:
    def test_morning_format_contains_sections(self):
        data = {
            "costs": {"total_usd": 2.41, "by_model": {"gpt-5": 1.22}, "entries": 14},
            "health": {"containers": {"rag-backend": "up"}, "http": {"RAG": {"ok": True, "latency_ms": 42}}},
            "queue": {"new_last_24h": 5},
            "extras": [{"file": "thing.log", "last": "entry X"}],
        }
        out = hermes_bridge._pd_format_digest("morning", data)
        assert "Morning" in out
        assert "$2.41" in out
        assert "rag-backend" in out
        assert "RAG" in out
        assert "5" in out  # queue count

    def test_evening_format_contains_git(self):
        data = {
            "costs": {"total_usd": 4.0, "by_model": {}, "entries": 0},
            "git": {
                "RAG": {"commits": ["abc1234 feat: x"], "files_changed": 3},
                "trading-app": {"error": "repo missing"},
            },
            "highlights": [{"file": "x.py", "preview": "• leak"}],
            "research": {"count": 2, "last_topic": "RRF"},
            "extras": [],
        }
        out = hermes_bridge._pd_format_digest("evening", data)
        assert "Evening" in out
        assert "RAG" in out
        assert "feat: x" in out
        assert "trading-app" in out
        assert "leak" in out
        assert "RRF" in out

    def test_sanitizes_output(self):
        data = {
            "costs": {"total_usd": 0.0, "by_model": {}, "entries": 0},
            "health": {"containers": {}, "http": {}},
            "queue": {"new_last_24h": 0},
            "extras": [{"file": "leak.log", "last": "Bearer abcdefghijklmnop12345"}],
        }
        out = hermes_bridge._pd_format_digest("morning", data)
        assert "abcdefghijklmnop12345" not in out
        assert "REDACTED" in out

    def test_output_within_telegram_budget(self):
        # Force a large dataset
        data = {
            "costs": {"total_usd": 100.0, "by_model": {f"m{i}": 1.0 for i in range(50)}, "entries": 100},
            "git": {p: {"commits": [f"abc{i} commit {i}" for i in range(20)], "files_changed": 50}
                    for p in hermes_bridge._PD_PROJECTS},
            "highlights": [{"file": f"f{i}.py", "preview": "x" * 80} for i in range(10)],
            "research": {"count": 100, "last_topic": "y" * 100},
            "extras": [{"file": f"e{i}.log", "last": "z" * 180} for i in range(10)],
        }
        out = hermes_bridge._pd_format_digest("evening", data)
        assert len(out) <= 3800


class TestHandleProjectDigest:
    def test_dispatches_morning_mode(self, tmp_path, monkeypatch):
        # Stub out heavy parts
        monkeypatch.setattr(hermes_bridge, "_pd_parse_costs", lambda since_hours: {"total_usd": 0.0, "by_model": {}, "entries": 0})
        monkeypatch.setattr(hermes_bridge, "_pd_health_check", lambda: {"containers": {}, "http": {}})
        monkeypatch.setattr(hermes_bridge, "_pd_review_learn_queue", lambda: {"new_last_24h": 7})
        monkeypatch.setattr(hermes_bridge, "_pd_scan_extras", lambda since_hours: [])

        out = hermes_bridge._handle_project_digest("project-digest-morning")
        assert "Morning" in out
        assert "7" in out

    def test_dispatches_evening_mode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hermes_bridge, "_pd_parse_costs", lambda since_hours: {"total_usd": 0.0, "by_model": {}, "entries": 0})
        monkeypatch.setattr(hermes_bridge, "_pd_git_log_since", lambda hours: {})
        monkeypatch.setattr(hermes_bridge, "_pd_review_learn_highlights", lambda last_n: [])
        monkeypatch.setattr(hermes_bridge, "_pd_research_log_since", lambda hours: {"count": 0, "last_topic": ""})
        monkeypatch.setattr(hermes_bridge, "_pd_scan_extras", lambda since_hours: [])

        out = hermes_bridge._handle_project_digest("project-digest-evening")
        assert "Evening" in out

    def test_lock_blocks_second_run(self, tmp_path, monkeypatch):
        # Hold a lock manually, then ensure handler returns "skipping"
        lock_path = tmp_path / ".digest-project-digest-morning.lock"
        # Use the real pid (alive process) so reclaim doesn't fire
        lock_path.write_text(str(os.getpid()))

        out = hermes_bridge._handle_project_digest("project-digest-morning")
        assert "already running" in out.lower() or "skip" in out.lower()
```

Dodać import na górze test file:
```python
import os
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestFormatDigest tests/test_project_digest.py::TestHandleProjectDigest -v
```

Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def _pd_append_section(lines: list[str], section: list[str], budget_remaining: int) -> int:
    """Append section if it fits; truncate with '… (+N more)' if not. Returns new budget."""
    section_size = sum(len(s) + 1 for s in section)
    if section_size <= budget_remaining:
        lines.extend(section)
        return budget_remaining - section_size
    used = 0
    for i, s in enumerate(section):
        if used + len(s) + 1 > budget_remaining - 30:
            lines.append(f"… (+{len(section) - i} more)")
            return 0
        lines.append(s)
        used += len(s) + 1
    return budget_remaining - used


def _pd_format_digest(mode: str, data: dict) -> str:
    """Build digest string ≤3800 chars, sanitized."""
    BUDGET = 3800
    header_icon = "🌅" if mode == "morning" else "🌙"
    title = "Morning" if mode == "morning" else "Evening"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines: list[str] = [
        f"{header_icon} Project Digest — {title} ({date_str})",
        "",
    ]
    budget = BUDGET - sum(len(s) + 1 for s in lines)

    # Costs
    costs = data.get("costs", {})
    cost_lines = [
        f"💰 Costs (last {'24h' if mode == 'morning' else 'today'})",
        f"  Total: ${costs.get('total_usd', 0.0):.2f}  (entries: {costs.get('entries', 0)})",
    ]
    for model, v in sorted(costs.get("by_model", {}).items(), key=lambda x: -x[1])[:5]:
        cost_lines.append(f"  {model}: ${v:.2f}")
    cost_lines.append("")
    budget = _pd_append_section(lines, cost_lines, budget)

    if mode == "morning":
        health = data.get("health", {})
        h_lines = ["📊 Health", "  Containers:"]
        for name, state in sorted(health.get("containers", {}).items()):
            icon = "🟢" if state == "up" else "🔴"
            h_lines.append(f"    {icon} {name} ({state})")
        h_lines.append("  HTTP:")
        for name, info in sorted(health.get("http", {}).items()):
            if info.get("ok"):
                h_lines.append(f"    🟢 {name} ({info.get('latency_ms', 0)}ms)")
            else:
                h_lines.append(f"    🔴 {name} ({info.get('error', 'down')})")
        h_lines.append("")
        budget = _pd_append_section(lines, h_lines, budget)

        queue = data.get("queue", {})
        q_lines = [
            "🔍 Review-learn queue",
            f"  new last 24h: {queue.get('new_last_24h', 0)}",
            "",
        ]
        budget = _pd_append_section(lines, q_lines, budget)
    else:
        # Evening: git + highlights + research
        git = data.get("git", {})
        g_lines = ["📦 Git activity (last 12h)"]
        for proj, info in sorted(git.items()):
            if "error" in info:
                g_lines.append(f"  ⚠️ {proj}: {info['error']}")
                continue
            commits = info.get("commits", [])
            files = info.get("files_changed", 0)
            g_lines.append(f"  {proj}: {len(commits)} commits, {files} files")
            for c in commits[:2]:
                g_lines.append(f"    🔝 {c[:80]}")
        g_lines.append("")
        budget = _pd_append_section(lines, g_lines, budget)

        highlights = data.get("highlights", [])
        if highlights:
            h_lines = ["🎯 Review-learn highlights"]
            for h in highlights:
                h_lines.append(f"  • {h.get('file', '?')} — {h.get('preview', '')}")
            h_lines.append("")
            budget = _pd_append_section(lines, h_lines, budget)

        research = data.get("research", {})
        if research.get("count", 0) > 0:
            r_lines = [
                "🔬 Research (last 12h)",
                f"  {research['count']} entries, last: {research.get('last_topic', '')[:80]}",
                "",
            ]
            budget = _pd_append_section(lines, r_lines, budget)

    # Extras (both modes)
    extras = data.get("extras", [])
    if extras:
        e_lines = ["📋 Extras"]
        for e in extras:
            e_lines.append(f"  [{e['file']}] {e['last']}")
        e_lines.append("")
        budget = _pd_append_section(lines, e_lines, budget)

    # Signals placeholder
    lines.append("🚨 Signals: (none)")

    result = "\n".join(lines)
    if len(result) > BUDGET:
        result = result[:BUDGET - 20] + "\n… (truncated)"
    return _pd_sanitize(result)


def _handle_project_digest(skill_name: str) -> str:
    """Main entry point. Skill_name = project-digest-morning | project-digest-evening."""
    mode = "morning" if "morning" in skill_name else "evening"
    cutoff_h = 24 if mode == "morning" else 12

    with _pd_digest_lock(skill_name) as acquired:
        if not acquired:
            return f"⏭️ digest {skill_name} already running, skipping"

        data: dict = {
            "costs": _pd_parse_costs(since_hours=cutoff_h),
        }
        if mode == "morning":
            data["health"] = _pd_health_check()
            data["queue"] = _pd_review_learn_queue()
        else:
            data["git"] = _pd_git_log_since(hours=12)
            data["highlights"] = _pd_review_learn_highlights(last_n=2)
            data["research"] = _pd_research_log_since(hours=12)
        data["extras"] = _pd_scan_extras(since_hours=cutoff_h)

        return _pd_format_digest(mode, data)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestFormatDigest tests/test_project_digest.py::TestHandleProjectDigest -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): add _pd_format_digest + _handle_project_digest entry point"
```

---

## Task 9: Wire crony + routing

**Files:**
- Modify: `hermes/bridge/hermes_bridge.py` (sekcja `_CRONS` koło linii 146, routery koło 2159 i 2935)

- [ ] **Step 1: Dodać cron entries**

W `_CRONS` (przed zamykającym `}` koło linii 145) dopisać:

```python
    "project-digest-morning": {
        "interval_s": 86400,
        "run_at_hour": 8,
        "enabled": True,
        "last_run": 0.0,
        "description": "Project digest (morning, 8:00 UTC)",
        "notify": "always",
    },
    "project-digest-evening": {
        "interval_s": 86400,
        "run_at_hour": 20,
        "enabled": True,
        "last_run": 0.0,
        "description": "Project digest (evening, 20:00 UTC)",
        "notify": "always",
    },
```

- [ ] **Step 2: Dodać routing w `_dispatch_cron_skill`**

Znaleźć w funkcji `_dispatch_cron_skill` (koło linii 2147-2177) sekcję `if skill_name == "daily-digest"`. Dodać przed nią:

```python
    if skill_name in ("project-digest-morning", "project-digest-evening"):
        return _handle_project_digest(skill_name)
```

- [ ] **Step 3: Dodać routing dla manualnego wywołania**

W `_dispatch_skill_text` (koło linii 2935 — sekcja `if skill_name in ("daily-digest", "digest"):`) dodać:

```python
        if skill_name in ("project-digest-morning", "project-digest-evening", "project-digest"):
            # Manual override: bare "project-digest" defaults to morning for testing
            target = skill_name if skill_name != "project-digest" else "project-digest-morning"
            return _handle_project_digest(target)
```

- [ ] **Step 4: Test routingu — smoke test**

```python
class TestRouting:
    def test_cron_dispatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hermes_bridge, "_pd_parse_costs", lambda since_hours: {"total_usd": 0.0, "by_model": {}, "entries": 0})
        monkeypatch.setattr(hermes_bridge, "_pd_health_check", lambda: {"containers": {}, "http": {}})
        monkeypatch.setattr(hermes_bridge, "_pd_review_learn_queue", lambda: {"new_last_24h": 0})
        monkeypatch.setattr(hermes_bridge, "_pd_scan_extras", lambda since_hours: [])

        result = hermes_bridge._dispatch_cron_skill("project-digest-morning")
        assert "Morning" in result

    def test_crons_registered(self):
        assert "project-digest-morning" in hermes_bridge._CRONS
        assert "project-digest-evening" in hermes_bridge._CRONS
        assert hermes_bridge._CRONS["project-digest-morning"]["run_at_hour"] == 8
        assert hermes_bridge._CRONS["project-digest-evening"]["run_at_hour"] == 20
```

Run:
```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py::TestRouting -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add hermes/bridge/hermes_bridge.py hermes/bridge/tests/test_project_digest.py
git commit -m "feat(hermes): wire project-digest morning/evening crons + routing"
```

---

## Task 10: Skill documentation

**Files:**
- Create: `hermes/skills/project-digest.md`

- [ ] **Step 1: Write skill file**

Plik `hermes/skills/project-digest.md`:

```markdown
# Project Digest

## When to use
Automatically via cron at **8:00 UTC** (morning) and **20:00 UTC** (evening).
Manually via Telegram: `/skill project-digest-morning`, `/skill project-digest-evening`, or `/skill project-digest` (defaults to morning).

## Flow
1. Acquire singleton lock (`_pd_digest_lock`) — skip if other digest still running
2. Aggregate data per mode:
   - **morning** (24h window): costs, health (docker + HTTP), review-learn queue, extras
   - **evening** (12h window): costs, git activity, review-learn highlights, research log, extras
3. Format ≤3800 chars output with graceful section truncation
4. Sanitize secrets (sk-, Bearer, JWT, api_key=, hex≥40, env-var names)
5. Send to Telegram via outbox

## Projects scanned (git activity)
- RAG (`/workspace/ro/RAG`)
- Selfmadeagent (`/workspace/ro/Selfmadeagent`)
- VINhunter (`/workspace/ro/VIN OSINT/vinhunter`)
- trading-app (`/workspace/ro/trading-app`)
- hermes (`/workspace/ro/hermes`)

Soft-fail: missing repo → `⚠️ <name>: repo missing`, rest of digest continues.

## HTTP endpoints probed
- RAG: `http://rag-backend:8000/health`
- Selfmadeagent: `http://selfmadeagent:8080/health`

## Extras gate
- Allowlist patterns: `*.log`, `*.jsonl` in `/audit/`
- Denylist: `auth.log`, `secrets.json`, `.env`, `cdp.log`, `cdp_readonly.log`, `llm-proxy.jsonl`, `costs.jsonl`, `review-learn.log`, `cron.log`, `research.log`, `watcher-heartbeat.txt`, `self-learn.log`
- Cap: 10 entries, 1 per file, 180 chars per entry, 16KB line max
- JSONL: pretty-extract `message`/`event`/`type` if present

## Security boundary
Treat all digest output as leaving the system (Telegram = cloud, mobile, screenshots, forwarding). `_pd_sanitize()` masks common secret patterns. Endpoints + project paths are hardcoded — never accept paths/URLs from Telegram input.

## Watch out for
- UTC timezone everywhere (cron `run_at_hour: 8` = 8:00 UTC ≈ 10:00 CEST)
- Mode detection is via `skill_name` substring (`morning`/`evening`) — not via `datetime.now().hour`, which would misbehave under lock delay
- Docker.sock is mounted into hermes container — compromise = root host (known, out of scope to harden in this skill)
- If `costs.jsonl` grows beyond 5000 lines/day, switch to byte-offset checkpointing (currently tail-only via `deque(f, maxlen=5000)`)
```

- [ ] **Step 2: Commit**

```bash
git add hermes/skills/project-digest.md
git commit -m "docs(hermes): add project-digest skill description"
```

---

## Task 11: Manual integration smoke test

**Files:**
- No code changes — pure verification.

- [ ] **Step 1: Run full test suite**

```bash
cd hermes/bridge && python -m pytest tests/test_project_digest.py -v
```

Expected: all tests passing (≥30 tests across 9 classes).

- [ ] **Step 2: Run existing test suite to verify no regressions**

```bash
cd hermes/bridge && python -m pytest tests/ -v
```

Expected: all pre-existing tests still passing.

- [ ] **Step 3: Manual smoke test via Hermes (requires running stack)**

Jeśli Hermes Docker stack jest uruchomiony, wysłać do bota:

```
/skill project-digest-morning
```

Następnie:

```
/skill project-digest-evening
```

Verify:
- Otrzymany Telegram message ma format z sekcjami (💰 Costs, 📊 Health / 📦 Git, 📋 Extras)
- Brak tokenów (sk-, Bearer, JWT, długie hexy) w outputcie
- Długość ≤3800 chars (max 4096 limit Telegrama nie przekroczony)
- Drugi run w krótkim czasie → "⏭️ already running, skipping" jeśli pierwszy nie zakończył; lub poprawny digest jeśli pierwszy zwolnił lock

Jeśli Hermes nie jest uruchomiony, pominąć ten krok — testy unit pokrywają każdą gałąź logiki.

- [ ] **Step 4: No commit needed** — verification only.

---

## Self-Review

### Spec coverage check

| Spec sekcja | Task |
|-------------|------|
| 1a Threat model (sanitizer, denylist, hardcoded endpoints/paths) | Task 1, 5, 8 |
| 2.1 Files | Task 9 (cron entries), Task 10 (skill md), Task 8 (handler) |
| 2.2 Crony | Task 9 |
| 2.3 Timezone UTC | Task 8 (uses `datetime.now(timezone.utc)`) |
| 3.1 Morning content | Task 8 (`_pd_format_digest("morning", ...)`) |
| 3.2 Evening content | Task 8 |
| 4.1 Handler | Task 8 |
| 4.2 git_log_since + shortstat + assert int | Task 3 |
| 4.3 parse_costs + iterator deque + 16KB cap | Task 2 |
| 4.4 health_check `docker ps -a` + states | Task 4 |
| 4.5 scan_extras allowlist/denylist + JSONL pretty | Task 5 |
| 4.6 review_learn_highlights | Task 7 |
| 4.7 review_learn_queue | Task 7 |
| 4.8 research_log_since | Task 7 |
| 4.9 format_digest + section truncation + sanitizer | Task 8 |
| 5 Lockfile atomic reclaim + O_NOFOLLOW | Task 6 |
| 7 Manual test via Telegram | Task 11 |

Wszystkie sekcje pokryte.

### Placeholder scan
Brak TBD/TODO/"appropriate error handling". Każdy step ma konkretny kod albo konkretną komendę z expected output.

### Type consistency
- `_pd_parse_costs` → `dict` z kluczami `total_usd`, `by_model`, `entries` — używane spójnie w Task 8 (`costs.get('total_usd', 0.0)`)
- `_pd_health_check` → `{"containers": dict, "http": dict}` — pasuje do Task 8
- `_pd_git_log_since` → `dict[str, dict]` per projekt — pasuje
- `_pd_scan_extras` → `list[{"file": str, "last": str}]` — pasuje do extras section
- `_pd_review_learn_highlights` → `list[{"file": str, "preview": str}]` — pasuje
- `_pd_digest_lock` → context manager yielding `bool` — `Task 8` używa `with ... as acquired:`

Wszystko spójne.
