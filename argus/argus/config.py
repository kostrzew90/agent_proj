import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    db_url: str = os.getenv("ARGUS_DB_URL", "sqlite:///argus.db")
    watchlist_path: str = os.getenv("ARGUS_WATCHLIST", "config/watchlist.yaml")
    sources_path: str = os.getenv("ARGUS_SOURCES", "config/sources.yaml")

settings = Settings()
