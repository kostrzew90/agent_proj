import os
import pytest
from unittest.mock import patch, MagicMock

from server import _call_gemini


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

    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as MockModel:
        instance = MockModel.return_value
        instance.generate_content.return_value = mock_response

        result = _call_gemini("What is AI?", "gemini-2.0-flash", None, 4096)

    assert result == "Mocked Gemini response"


def test_call_gemini_with_system_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mock_response = MagicMock()
    mock_response.text = "Response with system prompt"

    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as MockModel:
        instance = MockModel.return_value
        instance.generate_content.return_value = mock_response

        result = _call_gemini("hello", "gemini-2.0-flash", "You are a helpful assistant", 4096)

        assert result == "Response with system prompt"
        MockModel.assert_called_once_with(
            "gemini-2.0-flash",
            system_instruction="You are a helpful assistant"
        )


def test_call_gemini_returns_error_on_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    with patch("google.generativeai.configure"), \
         patch("google.generativeai.GenerativeModel") as MockModel:
        instance = MockModel.return_value
        instance.generate_content.side_effect = Exception("API quota exceeded")

        result = _call_gemini("hello", "gemini-2.0-flash", None, 4096)

    assert result.startswith("ERROR:")
    assert "API quota exceeded" in result
