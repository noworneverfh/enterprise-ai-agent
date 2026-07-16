from functools import lru_cache
from pathlib import Path

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance."""

    return Settings()


settings = get_settings()
