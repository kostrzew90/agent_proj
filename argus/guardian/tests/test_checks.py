from unittest.mock import MagicMock, patch
import pytest
import docker


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


# ── check_container_liveness ─────────────────────────────────────────────────

class TestCheckContainerLiveness:
    def _make_docker_client(self, statuses=None, raise_not_found=None):
        """statuses: dict of container_name -> status string"""
        statuses = statuses or {}
        client = MagicMock()
        _cache: dict = {}

        def get_container(name):
            if raise_not_found and name in raise_not_found:
                raise docker.errors.NotFound(name)
            if name not in _cache:
                c = MagicMock()
                c.status = statuses.get(name, "running")
                _cache[name] = c
            return _cache[name]

        client.containers.get.side_effect = get_container
        return client

    @patch("checks.docker.from_env")
    def test_container_not_found_returns_known_issue(self, mock_docker):
        mock_docker.return_value = self._make_docker_client(
            raise_not_found=["argus-app"]
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "not found" in result.message

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_container_stopped_restarts_and_known_issue(self, mock_docker, mock_get):
        client = self._make_docker_client(statuses={"argus-app": "exited"})
        mock_docker.return_value = client
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "Restarted" in result.message
        client.containers.get("argus-app").restart.assert_called_once()

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_health_500_restarts_app_and_known_issue(self, mock_docker, mock_get):
        client = self._make_docker_client(
            statuses={"argus-app": "running", "argus-liq-listener": "running"}
        )
        mock_docker.return_value = client
        mock_get.return_value = MagicMock(
            status_code=500,
            json=MagicMock(return_value={"status": "error"}),
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.KNOWN_ISSUE
        assert "health failed" in result.message

    @patch("checks.httpx.get")
    @patch("checks.docker.from_env")
    def test_all_ok_returns_ok(self, mock_docker, mock_get):
        client = self._make_docker_client(
            statuses={"argus-app": "running", "argus-liq-listener": "running"}
        )
        mock_docker.return_value = client
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "ok"}),
        )
        from checks import check_container_liveness, Status
        result = check_container_liveness({})
        assert result.status == Status.OK


# ── check_queue_runaway ───────────────────────────────────────────────────────

class TestCheckQueueRunaway:
    def _make_conn(self, depth):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (depth,)
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    @patch("checks.update_state")
    def test_growth_under_30min_returns_ok(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=50)
        state = {
            "last_queue_depth": 40,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=10),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK

    @patch("checks.update_state")
    def test_growth_over_30min_returns_known_issue(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=100)
        state = {
            "last_queue_depth": 40,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=35),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.KNOWN_ISSUE
        assert "30min+" in result.message

    @patch("checks.update_state")
    def test_depth_drops_resets_growth_start(self, mock_update):
        from datetime import datetime, timezone, timedelta
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=20)
        state = {
            "last_queue_depth": 50,
            "last_queue_growth_start": datetime.now(timezone.utc) - timedelta(minutes=40),
        }
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK
        # update_state called with last_queue_growth_start=None
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs.get("last_queue_growth_start") is None

    @patch("checks.update_state")
    def test_first_run_no_growth_start_returns_ok(self, mock_update):
        from checks import check_queue_runaway, Status
        conn = self._make_conn(depth=10)
        state = {"last_queue_depth": 0, "last_queue_growth_start": None}
        result = check_queue_runaway(conn, state)
        assert result.status == Status.OK
