import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from server import (
    _call_gemini,
    _call_openrouter,
    _call_ollama,
    _weekly_spent,
    _budget_remaining,
    _record_cost,
    _week_start_utc,
    ask_auto,
    budget_status,
    COST_LOG,
    AUDIT_LOG,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _redirect_audit(tmp_path, monkeypatch):
    """Redirect all audit/cost I/O to a temp dir for every test."""
    monkeypatch.setenv("HERMES_AUDIT_DIR", str(tmp_path))
    # Patch module-level path constants so helpers use the temp dir
    import server
    monkeypatch.setattr(server, "COST_LOG", tmp_path / "costs.jsonl")
    monkeypatch.setattr(server, "AUDIT_LOG", tmp_path / "llm-proxy.jsonl")
    yield


# ---------------------------------------------------------------------------
# _call_gemini
# ---------------------------------------------------------------------------

def test_call_gemini_no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = _call_gemini("hello", "gemini-2.0-flash", None, 4096)
    assert result == "ERROR: GEMINI_API_KEY not set"


def test_call_gemini_returns_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.text = "Mocked Gemini response"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        result = _call_gemini("What is AI?", "gemini-2.0-flash", None, 4096)

    assert result == "Mocked Gemini response"


def test_call_gemini_with_system_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.text = "Response with system prompt"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        result = _call_gemini("hello", "gemini-2.0-flash", "You are a helpful assistant", 4096)

    assert result == "Response with system prompt"


def test_call_gemini_returns_error_on_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API quota exceeded")

    with patch("google.genai.Client", return_value=mock_client):
        result = _call_gemini("hello", "gemini-2.0-flash", None, 4096)

    assert result.startswith("ERROR:")
    assert "API quota exceeded" in result


# ---------------------------------------------------------------------------
# _call_openrouter
# ---------------------------------------------------------------------------


def test_call_openrouter_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = _call_openrouter("hello", "meta-llama/llama-4-maverick:free", None, 4096)
    assert result == "ERROR: OPENROUTER_API_KEY not set"


def test_call_openrouter_returns_content(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Mocked OpenRouter response"}}]
    }

    with patch("requests.post", return_value=mock_response):
        result = _call_openrouter("What is AI?", "meta-llama/llama-4-maverick:free", None, 4096)

    assert result == "Mocked OpenRouter response"


def test_call_openrouter_with_system_prompt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        _call_openrouter("hello", "meta-llama/llama-4-maverick:free", "Be concise", 4096)

        call_kwargs = mock_post.call_args
        messages = call_kwargs.kwargs["json"]["messages"]
        assert messages[0] == {"role": "system", "content": "Be concise"}
        assert messages[1] == {"role": "user", "content": "hello"}


def test_call_openrouter_returns_error_on_exception(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")

    with patch("requests.post", side_effect=Exception("Connection timeout")):
        result = _call_openrouter("hello", "meta-llama/llama-4-maverick:free", None, 4096)

    assert result.startswith("ERROR:")
    assert "Connection timeout" in result


def test_call_openrouter_passes_timeout(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        _call_openrouter("hello", "meta-llama/llama-4-maverick:free", None, 4096)

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("timeout") == 60


# ---------------------------------------------------------------------------
# _call_ollama
# ---------------------------------------------------------------------------

def test_call_ollama_laptop_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_LAPTOP_URL", raising=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "ollama reply"}}

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = _call_ollama("hi", "qwen2.5-coder:3b", None, location="laptop")
        assert result == "ollama reply"
        url = mock_post.call_args.args[0]
        assert "host.docker.internal:11434" in url


def test_call_ollama_mac_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAC_URL", raising=False)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "mac reply"}}

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = _call_ollama("hi", "qwen3:4b", None, location="mac")
        assert result == "mac reply"
        url = mock_post.call_args.args[0]
        assert "100.73.220.16:11434" in url


def test_call_ollama_custom_env_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_LAPTOP_URL", "http://my-laptop:11434")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "ok"}}

    with patch("requests.post", return_value=mock_response) as mock_post:
        _call_ollama("hi", "model", None, location="laptop")
        url = mock_post.call_args.args[0]
        assert "my-laptop:11434" in url


def test_call_ollama_error_on_exception():
    with patch("requests.post", side_effect=Exception("Connection refused")):
        result = _call_ollama("hi", "qwen2.5-coder:3b", None)
    assert result.startswith("ERROR:")
    assert "Connection refused" in result


def test_call_ollama_includes_system_prompt():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"message": {"content": "ok"}}

    with patch("requests.post", return_value=mock_response) as mock_post:
        _call_ollama("hello", "qwen2.5-coder:3b", "Be terse")
        body = mock_post.call_args.kwargs["json"]
        messages = body["messages"]
        assert messages[0] == {"role": "system", "content": "Be terse"}
        assert messages[1] == {"role": "user", "content": "hello"}


# ---------------------------------------------------------------------------
# Cost tracking: _weekly_spent / _budget_remaining
# ---------------------------------------------------------------------------

def _write_cost_entry(cost_log: Path, ts: datetime, cost: float) -> None:
    entry = {
        "ts": ts.isoformat(),
        "tool": "ask_auto",
        "model": "gemini-2.0-flash",
        "tokens_in": 10,
        "tokens_out": 10,
        "cost_usd": cost,
        "caller": None,
    }
    with cost_log.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def test_weekly_spent_empty(tmp_path):
    import server
    server.COST_LOG  # already redirected by fixture
    # No file exists → 0
    result = _weekly_spent()
    assert result == 0.0


def test_weekly_spent_sums_current_week(tmp_path):
    import server
    now = datetime.now(timezone.utc)
    week_start = _week_start_utc()
    # Entry from this week
    _write_cost_entry(server.COST_LOG, now, 1.5)
    # Entry from last week (before week_start)
    last_week = week_start - timedelta(days=1)
    _write_cost_entry(server.COST_LOG, last_week, 5.0)

    result = _weekly_spent()
    assert result == pytest.approx(1.5)


def test_weekly_spent_ignores_old_entries(tmp_path):
    import server
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _write_cost_entry(server.COST_LOG, old_ts, 99.0)
    assert _weekly_spent() == 0.0


def test_budget_remaining_default_cap(monkeypatch):
    monkeypatch.delenv("WEEKLY_BUDGET_USD", raising=False)
    import server
    # No spend
    result = _budget_remaining()
    assert result == pytest.approx(10.0)


def test_budget_remaining_accounts_for_spend(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "5")
    import server
    now = datetime.now(timezone.utc)
    _write_cost_entry(server.COST_LOG, now, 3.0)
    result = _budget_remaining()
    assert result == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# ask_auto routing
# ---------------------------------------------------------------------------

def test_ask_auto_easy_routes_to_laptop_ollama(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    with patch("server._call_ollama", return_value="laptop answer") as mock_ollama:
        result = ask_auto("hello", complexity="easy")
    assert result == "laptop answer"
    mock_ollama.assert_called_once()
    _, kwargs = mock_ollama.call_args
    assert kwargs.get("location") == "laptop" or mock_ollama.call_args.args[3] == "laptop"


def test_ask_auto_medium_routes_to_mac(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    with patch("server._call_ollama", return_value="mac answer") as mock_ollama:
        result = ask_auto("hello", complexity="medium")
    assert result == "mac answer"
    call_args = mock_ollama.call_args
    location = call_args.kwargs.get("location") or call_args.args[3]
    assert location == "mac"


def test_ask_auto_medium_falls_back_to_laptop_on_error(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    responses = ["ERROR: mac down", "laptop fallback"]
    with patch("server._call_ollama", side_effect=responses) as mock_ollama:
        result = ask_auto("hello", complexity="medium")
    assert result == "laptop fallback"
    assert mock_ollama.call_count == 2


def test_ask_auto_hard_routes_to_gemini(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("server._call_gemini", return_value="gemini answer") as mock_gemini, \
         patch("server._call_openrouter") as mock_or:
        result = ask_auto("hello", complexity="hard")
    assert result == "gemini answer"
    mock_gemini.assert_called_once()
    mock_or.assert_not_called()


def test_ask_auto_hard_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    with patch("server._call_gemini", return_value="ERROR: quota"), \
         patch("server._call_openrouter", return_value="openrouter answer") as mock_or:
        result = ask_auto("hello", complexity="hard")
    assert result == "openrouter answer"
    mock_or.assert_called_once()


def test_ask_auto_budget_exhausted(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "1")
    import server
    now = datetime.now(timezone.utc)
    _write_cost_entry(server.COST_LOG, now, 2.0)  # spent > cap
    result = ask_auto("hello", complexity="easy")
    assert result.startswith("ERROR:")
    assert "budget" in result.lower()


def test_ask_auto_records_real_provider_not_auto(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    with patch("server._call_gemini", return_value="gemini answer"), \
         patch("llmops_client.record") as mock_record:
        ask_auto("hello", complexity="medium")
    mock_record.assert_called_once()
    _, kwargs = mock_record.call_args
    provider = kwargs.get("provider") if kwargs else mock_record.call_args.args[0]
    assert provider != "auto"
    assert provider == "gemini"


# ---------------------------------------------------------------------------
# budget_status
# ---------------------------------------------------------------------------

def test_budget_status_shape(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    result = budget_status()
    assert "weekly_cap_usd" in result
    assert "spent_this_week_usd" in result
    assert "remaining_usd" in result
    assert "calls_this_week" in result
    assert "week_start_utc" in result
    assert result["weekly_cap_usd"] == 10.0
    assert result["remaining_usd"] == pytest.approx(10.0)
    assert result["calls_this_week"] == 0


def test_budget_status_reflects_spend(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    import server
    now = datetime.now(timezone.utc)
    _write_cost_entry(server.COST_LOG, now, 2.5)
    _write_cost_entry(server.COST_LOG, now, 1.0)
    result = budget_status()
    assert result["spent_this_week_usd"] == pytest.approx(3.5)
    assert result["remaining_usd"] == pytest.approx(6.5)
    assert result["calls_this_week"] == 2


# ---------------------------------------------------------------------------
# Audit log written on success and error
# ---------------------------------------------------------------------------

def test_audit_log_written_on_success(monkeypatch):
    import server
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    with patch("server._call_ollama", return_value="ok"):
        ask_auto("test prompt", complexity="easy")
    assert server.AUDIT_LOG.exists()
    lines = server.AUDIT_LOG.read_text().strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[-1])
    assert entry["tool"] == "ask_auto"
    assert entry["error"] is None
    assert entry["prompt_len"] == len("test prompt")


def test_audit_log_written_on_error(monkeypatch):
    import server
    monkeypatch.setenv("WEEKLY_BUDGET_USD", "10")
    with patch("server._call_ollama", return_value="ERROR: something went wrong"):
        ask_auto("bad prompt", complexity="easy")
    lines = server.AUDIT_LOG.read_text().strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["error"] is not None
    assert entry["error"].startswith("ERROR:")


# ---------------------------------------------------------------------------
# SSE transport selection
# ---------------------------------------------------------------------------

class TestSSETransport:
    """Verify that MCP_TRANSPORT=sse causes mcp.run(transport='sse')."""

    def test_sse_transport_calls_run_with_sse(self, monkeypatch):
        import server as srv
        monkeypatch.setenv("MCP_TRANSPORT", "sse")
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MCP_PORT", "8000")

        calls = []

        def fake_run(transport="stdio", **kwargs):
            calls.append(transport)

        monkeypatch.setattr(srv.mcp, "run", fake_run)

        import os
        _transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
        if _transport == "sse":
            srv.mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
            srv.mcp.settings.port = int(os.environ.get("MCP_PORT", "8000"))
            srv.mcp.run(transport="sse")
        else:
            srv.mcp.run()

        assert calls == ["sse"], f"Expected run called with 'sse', got {calls}"

    def test_stdio_transport_calls_run_default(self, monkeypatch):
        import server as srv
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        calls = []

        def fake_run(transport="stdio", **kwargs):
            calls.append(transport)

        monkeypatch.setattr(srv.mcp, "run", fake_run)

        import os
        _transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
        if _transport == "sse":
            srv.mcp.run(transport="sse")
        else:
            srv.mcp.run()

        assert calls == ["stdio"], f"Expected run called with 'stdio', got {calls}"

    def test_sse_sets_host_and_port_on_settings(self, monkeypatch):
        import server as srv
        monkeypatch.setenv("MCP_TRANSPORT", "sse")
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MCP_PORT", "9090")
        monkeypatch.setattr(srv.mcp, "run", lambda **kw: None)

        import os
        _transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
        if _transport == "sse":
            srv.mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
            srv.mcp.settings.port = int(os.environ.get("MCP_PORT", "8000"))
            srv.mcp.run(transport="sse")

        assert srv.mcp.settings.host == "0.0.0.0"
        assert srv.mcp.settings.port == 9090


def test_record_cost_emits_to_llmops(monkeypatch):
    import llmops_client
    import server
    sent = []
    monkeypatch.setattr(llmops_client, "record", lambda **kw: sent.append(kw))
    monkeypatch.setattr(server, "_insert_pg", lambda **kw: None)

    server._record_cost("ask_openrouter", "google/gemma-3-27b-it:free",
                        100, 200, 0.0, skill="research", latency_ms=900, error=None)

    assert len(sent) == 1
    assert sent[0]["provider"] == "openrouter"
    assert sent[0]["model"] == "google/gemma-3-27b-it:free"
    assert sent[0]["tokens_estimated"] is True
    assert sent[0]["ok"] is True
