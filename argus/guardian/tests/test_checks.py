from unittest.mock import MagicMock, patch
import pytest


# ── telegram ─────────────────────────────────────────────────────────────────

class TestSendAlert:
    def test_no_token_does_nothing(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        import importlib, telegram
        importlib.reload(telegram)  # pick up cleared env
        with patch("httpx.post") as mock_post:
            telegram.send_alert("hello")
            mock_post.assert_not_called()

    def test_with_env_calls_post(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
        import importlib, telegram
        importlib.reload(telegram)
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            telegram.send_alert("test message")
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "tok123" in call_kwargs.args[0]
            assert call_kwargs.kwargs["json"]["chat_id"] == "chat456"
            assert call_kwargs.kwargs["json"]["text"] == "test message"

    def test_httpx_error_swallowed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
        import importlib, telegram
        importlib.reload(telegram)
        with patch("httpx.post", side_effect=Exception("network error")):
            telegram.send_alert("oops")  # must not raise


# ── CheckResult ───────────────────────────────────────────────────────────────

class TestCheckResult:
    def test_dataclass_defaults(self):
        from checks import CheckResult, Status
        r = CheckResult(name="foo", status=Status.OK, message="")
        assert r.remediation is None
        assert r.logs_snippet is None

    def test_all_fields(self):
        from checks import CheckResult, Status
        r = CheckResult(
            name="container_liveness",
            status=Status.KNOWN_ISSUE,
            message="restarted",
            remediation="docker restart app",
            logs_snippet="some logs",
        )
        assert r.name == "container_liveness"
        assert r.status == Status.KNOWN_ISSUE
