from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "Enterprise AI Agent Platform"
    app_version: str = "0.1.0"
    debug: bool = True
    database_url: str = "sqlite:///./enterprise_ai_agent.db"
    chroma_persist_directory: str = str(BACKEND_DIR / "chroma_db")
    chroma_collection_name: str = "knowledge_chunks"
    upload_directory: str = str(BACKEND_DIR / "uploads")
    max_upload_size: int = 5 * 1024 * 1024
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1200
    llm_json_mode: bool = True

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance."""

    return Settings()


settings = get_settings()
