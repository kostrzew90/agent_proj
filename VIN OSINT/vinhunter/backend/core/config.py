from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Database
    database_url: str = "postgresql+asyncpg://vinhunter:vinhunterpass@localhost:5436/vinhunter"

    # CORS — przechowywane jako string, parsowane przez property
    cors_origins: str = "http://localhost:3010"

    # Plugin timeouts
    plugin_default_timeout: int = 30
    captcha_timeout: int = 120

    # Playwright
    playwright_max_concurrent: int = 3

    # Proxy
    proxy_enabled: bool = False
    proxy_list: str = ""
    proxy_rotation: str = "round_robin"

    # API keys (optional)
    autoref_api_key: str = ""
    vincario_api_key: str = ""
    vincario_secret_key: str = ""

    # Logging
    log_level: str = "INFO"

    # Reports & screenshots dirs
    reports_dir: str = "/app/reports"
    screenshots_dir: str = "/app/screenshots"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def proxy_list_parsed(self) -> list[str]:
        if not self.proxy_list:
            return []
        return [p.strip() for p in self.proxy_list.split(",") if p.strip()]


settings = Settings()
