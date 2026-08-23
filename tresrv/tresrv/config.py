import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    gemini_api_key: str
    database_url: str
    evening_summary_hour: int = 21
    evening_summary_minute: int = 0
    pending_parse_interval_minutes: int = 2
    heartbeat_interval_minutes: int = 5
    max_pending_attempts: int = 5


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=int(os.environ["TELEGRAM_CHAT_ID"]),
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+psycopg2://tresrv:tresrv@db:5432/tresrv"
        ),
    )
