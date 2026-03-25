"""
RAG System — Configuration
All settings loaded from environment variables with sensible defaults.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class DatabaseSettings(BaseSettings):
    user: str = "rag"
    password: str = "ragpass"
    host: str = "rag-postgres"
    port: int = 5432
    name: str = "rag"

    model_config = {"env_prefix": "RAG_DB_"}

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    url: str = "redis://rag-redis:6379/0"

    model_config = {"env_prefix": "REDIS_"}


class AISettings(BaseSettings):
    ollama_url: str = "http://192.168.1.100:11434"
    whisper_url: str = "http://192.168.1.100:8002"

    llm_model: str = "qwen3:latest"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768
    judge_model: str = "qwen3:0.6b"

    model_config = {"env_prefix": ""}


class DoclingSettings(BaseSettings):
    """Docling document processing settings."""
    ocr_enabled: bool = True
    ocr_engine: str = "easyocr"  # easyocr, tesserocr, rapidocr
    pdf_backend: str = "docling"  # docling native PDF parser
    max_pages: int = 500

    model_config = {"env_prefix": "DOCLING_"}


class ChunkingSettings(BaseSettings):
    size: int = 512
    overlap: int = 102
    max_size: int = 1024
    min_size: int = 64

    model_config = {"env_prefix": "CHUNK_"}


class RetrievalSettings(BaseSettings):
    top_k: int = 10
    semantic_weight: float = 0.7
    bm25_weight: float = 0.3

    model_config = {"env_prefix": "RETRIEVAL_", "extra": "ignore"}


class AuthSettings(BaseSettings):
    jwt_secret: str = "change-me-to-random-secret-min-32-chars"
    jwt_expiry_hours: int = 24

    model_config = {"env_prefix": ""}


class CrawlSettings(BaseSettings):
    """mdream web crawler settings."""
    mdream_image: str = "harlanzw/mdream:latest"
    max_depth: int = 3
    driver: str = "fetch"  # fetch (static) or playwright (JS/SPA)
    max_pages: int = 100

    model_config = {"env_prefix": "CRAWL_", "extra": "ignore"}


class LangfuseSettings(BaseSettings):
    host: str = "http://rag-langfuse:3000"
    public_key: str = ""
    secret_key: str = ""

    model_config = {"env_prefix": "LANGFUSE_", "extra": "ignore"}


class WatchFolderSettings(BaseSettings):
    path: str = "/data/watch"
    enabled: bool = True

    model_config = {"env_prefix": "WATCH_FOLDER_"}


class AppSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "info"
    max_file_size_mb: int = 500
    upload_path: str = "/data/uploads"

    model_config = {"env_prefix": "APP_", "extra": "ignore"}


class Settings:
    """Aggregated settings — single import point."""

    def __init__(self):
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.ai = AISettings()
        self.docling = DoclingSettings()
        self.chunking = ChunkingSettings()
        self.retrieval = RetrievalSettings()
        self.auth = AuthSettings()
        self.crawl = CrawlSettings()
        self.langfuse = LangfuseSettings()
        self.watch_folder = WatchFolderSettings()
        self.app = AppSettings()


# Singleton
settings = Settings()
