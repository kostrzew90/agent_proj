import os
import pytest
from unittest.mock import patch, MagicMock

from server import _call_gemini, _call_openrouter


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
