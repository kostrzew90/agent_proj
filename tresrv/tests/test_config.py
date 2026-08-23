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


def test_load_settings_reads_optional_overrides_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("EVENING_SUMMARY_HOUR", "20")
    monkeypatch.setenv("EVENING_SUMMARY_MINUTE", "30")
    monkeypatch.setenv("PENDING_PARSE_INTERVAL_MINUTES", "3")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_MINUTES", "10")
    monkeypatch.setenv("MAX_PENDING_ATTEMPTS", "7")

    settings = load_settings()

    assert settings.evening_summary_hour == 20
    assert settings.evening_summary_minute == 30
    assert settings.pending_parse_interval_minutes == 3
    assert settings.heartbeat_interval_minutes == 10
    assert settings.max_pending_attempts == 7


def test_load_settings_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(KeyError):
        load_settings()
