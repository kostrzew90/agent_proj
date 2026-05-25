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
    ollama_url: str = "http://host.docker.internal:11434"
    whisper_url: str = "http://host.docker.internal:8002"

    llm_model: str = "qwen3:1.7b"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dimension: int = 1024
    judge_model: str = "qwen3:1.7b"

    # OpenRouter (optional — overrides Ollama for LLM/judge when set)
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.0-flash-001"
    openrouter_judge_model: str = "google/gemini-2.0-flash-001"

    # Groq (optional — fast Whisper API, free tier 7200s/day)
    groq_api_key: str = ""

    model_config = {"env_prefix": "", "extra": "ignore"}


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
    reranker_enabled: bool = True
    reranker_top_k: int = 5
    reranker_llm_weight: float = 0.7        # hybrid merge: 0.7 LLM + 0.3 RRF
    reranker_max_per_section: int = 2       # diversity cap
    reranker_content_truncate: int = 600    # chars sent to LLM per chunk

    model_config = {"env_prefix": "RETRIEVAL_", "extra": "ignore"}


class AuthSettings(BaseSettings):
    jwt_secret: str = "change-me-to-random-secret-min-32-chars"
    jwt_expiry_hours: int = 24

    model_config = {"env_prefix": ""}


class CrawlSettings(BaseSettings):
    """Web crawler settings (trafilatura-based, no external service)."""
    max_depth: int = 3
    max_pages: int = 100
    timeout: float = 30.0

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
