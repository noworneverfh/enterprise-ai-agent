from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "enterprise_ai_agent.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "Enterprise AI Agent Platform"
    app_version: str = "0.1.0"
    debug: bool = True
    database_url: str = DEFAULT_DATABASE_URL
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

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_database_url(cls, database_url: str) -> str:
        sqlite_prefix = "sqlite:///"

        if not database_url.startswith(sqlite_prefix):
            return database_url

        database_path = database_url.removeprefix(sqlite_prefix)

        if database_path in {":memory:", ""}:
            return database_url

        path = Path(database_path)
        if path.is_absolute():
            return f"{sqlite_prefix}{path.as_posix()}"

        return f"{sqlite_prefix}{(BACKEND_DIR / path).resolve().as_posix()}"

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
