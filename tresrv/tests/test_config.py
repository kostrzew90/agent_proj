import os
import pytest
from tresrv.config import load_settings


def test_load_settings_reads_required_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.telegram_bot_token == "abc123"
    assert settings.telegram_chat_id == 555
    assert settings.gemini_api_key == "gem-key"
    assert settings.database_url == "postgresql+psycopg2://tresrv:tresrv@db:5432/tresrv"
    assert settings.evening_summary_hour == 21


def test_load_settings_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(KeyError):
        load_settings()
