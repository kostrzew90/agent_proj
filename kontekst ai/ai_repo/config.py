"""Configuration management — loads .env + config.yaml with Pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

# Project root: kontekst ai/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml_config() -> dict:
    """Load config.yaml from project root."""
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml_config()


class DatabaseConfig(BaseSettings):
    host: str = Field(default=_yaml.get("database", {}).get("host", "localhost"))
    port: int = Field(default=_yaml.get("database", {}).get("port", 5435))
    user: str = Field(default=_yaml.get("database", {}).get("user", "ai_repo"))
    password: str = Field(default=_yaml.get("database", {}).get("password", "ai_repo_pass"))
    name: str = Field(default=_yaml.get("database", {}).get("name", "ai_repo"))

    model_config = {"env_prefix": "AI_REPO_DB_"}

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class OllamaConfig(BaseSettings):
    url: str = Field(default=_yaml.get("ollama", {}).get("url", "http://localhost:11434"))
    embed_model: str = Field(default=_yaml.get("ollama", {}).get("embed_model", "nomic-embed-text"))
    llm_model: str = Field(default=_yaml.get("ollama", {}).get("llm_model", "qwen3:8b"))
    embed_batch_size: int = Field(default=_yaml.get("ollama", {}).get("embed_batch_size", 32))
    timeout: int = Field(default=_yaml.get("ollama", {}).get("timeout", 120))

    model_config = {"env_prefix": "OLLAMA_"}


class LLMConfig(BaseSettings):
    provider: str = Field(default=_yaml.get("llm", {}).get("provider", "ollama"))
    temperature: float = Field(default=_yaml.get("llm", {}).get("temperature", 0.3))
    max_tokens: int = Field(default=_yaml.get("llm", {}).get("max_tokens", 2048))
    anthropic_api_key: Optional[str] = Field(default=None)

    model_config = {"env_prefix": "LLM_"}


class APIConfig(BaseSettings):
    host: str = Field(default=_yaml.get("api", {}).get("host", "0.0.0.0"))
    port: int = Field(default=_yaml.get("api", {}).get("port", 8100))

    model_config = {"env_prefix": "API_"}


class IndexingConfig(BaseSettings):
    default_repo_path: str = Field(
        default=_yaml.get("indexing", {}).get("default_repo_path", ".")
    )
    default_repo_id: str = Field(
        default=_yaml.get("indexing", {}).get("default_repo_id", "default")
    )
    ignore_patterns: list[str] = Field(
        default=_yaml.get("indexing", {}).get("ignore_patterns", [
            "node_modules", ".venv", "venv", "__pycache__", ".git",
            "dist", "build", ".egg-info", ".tox", ".mypy_cache", ".pytest_cache",
        ])
    )
    supported_extensions: list[str] = Field(
        default=_yaml.get("indexing", {}).get("supported_extensions", [
            ".py", ".yaml", ".yml", ".sql", ".md", ".txt", ".json",
            ".toml", ".cfg", ".ini", ".env", ".sh", ".bash", ".dockerfile",
            ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
        ])
    )


class RetrievalConfig(BaseSettings):
    top_k: int = Field(default=_yaml.get("retrieval", {}).get("top_k", 10))
    semantic_top_n: int = Field(default=_yaml.get("retrieval", {}).get("semantic_top_n", 50))
    keyword_top_n: int = Field(default=_yaml.get("retrieval", {}).get("keyword_top_n", 50))
    rrf_k: int = Field(default=_yaml.get("retrieval", {}).get("rrf_k", 60))
    context_max_tokens: int = Field(
        default=_yaml.get("retrieval", {}).get("context_max_tokens", 4096)
    )
    graph_expansion_depth: int = Field(
        default=_yaml.get("retrieval", {}).get("graph_expansion_depth", 1)
    )

    model_config = {"env_prefix": "RETRIEVAL_"}


class MemoryConfig(BaseSettings):
    auto_bootstrap: bool = Field(
        default=_yaml.get("memory", {}).get("auto_bootstrap", True)
    )
    default_confidence: float = Field(
        default=_yaml.get("memory", {}).get("default_confidence", 0.8)
    )


class PluginConfig(BaseSettings):
    directory: str = Field(
        default=_yaml.get("plugins", {}).get("directory", "plugins")
    )
    vendor_directory: str = Field(
        default=_yaml.get("plugins", {}).get("vendor_directory", "plugins/_vendor")
    )
    allow_network: bool = Field(
        default=_yaml.get("plugins", {}).get("allow_network", False)
    )
    allowlist: list[str] = Field(
        default=_yaml.get("plugins", {}).get("allowlist", ["plugin-logs", "plugin-template"])
    )

    model_config = {"env_prefix": "PLUGIN_"}


class Settings:
    """Aggregated settings — single access point for all config."""

    def __init__(self):
        # Load .env from project root if it exists
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            self._load_dotenv(env_path)

        self.database = DatabaseConfig()
        self.ollama = OllamaConfig()
        self.llm = LLMConfig()
        self.api = APIConfig()
        self.indexing = IndexingConfig()
        self.retrieval = RetrievalConfig()
        self.memory = MemoryConfig()
        self.plugins = PluginConfig()
        self.project_root = PROJECT_ROOT

    @staticmethod
    def _load_dotenv(path: Path):
        """Minimal .env loader — no extra dependency."""
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value


# Singleton
settings = Settings()
