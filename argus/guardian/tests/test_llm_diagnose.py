from unittest.mock import patch, MagicMock
import pytest


class TestDiagnose:
    def test_no_api_key_returns_unavailable(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)
        result = llm_diagnose.diagnose("some_anomaly", "some logs")
        assert "unavailable" in result

    def test_long_logs_truncated_to_50_lines(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        many_lines = "\n".join(f"line {i}" for i in range(200))
        captured_prompt = {}

        def mock_post(url, json, timeout):
            captured_prompt["prompt"] = json["contents"][0]["parts"][0]["text"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "diagnosis here"}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            llm_diagnose.diagnose("test_anomaly", many_lines)

        prompt_lines = captured_prompt["prompt"].count("\n")
        # 50 log lines + prompt overhead — rough check that it's not 200 lines
        assert "line 199" in captured_prompt["prompt"]  # last line present
        assert "line 0" not in captured_prompt["prompt"]  # first lines truncated

    def test_logs_truncated_to_10kb(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        # 200 lines of 100 chars each = 20KB, should truncate
        big_logs = "\n".join("x" * 100 for _ in range(200))
        captured_prompt = {}

        def mock_post(url, json, timeout):
            captured_prompt["text"] = json["contents"][0]["parts"][0]["text"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            llm_diagnose.diagnose("test_anomaly", big_logs)

        assert len(captured_prompt["text"]) <= 10_200  # 10KB logs + prompt header

    def test_httpx_error_returns_unavailable(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)
        with patch("httpx.post", side_effect=Exception("timeout")):
            result = llm_diagnose.diagnose("anomaly", "logs")
        assert "unavailable" in result

    def test_successful_call_returns_text(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        import importlib, llm_diagnose
        importlib.reload(llm_diagnose)

        def mock_post(url, json, timeout):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "Queue backed up due to rate limit."}]}}]
            }
            return resp

        with patch("httpx.post", side_effect=mock_post):
            result = llm_diagnose.diagnose("queue_runaway", "some logs")
        assert result == "Queue backed up due to rate limit."
