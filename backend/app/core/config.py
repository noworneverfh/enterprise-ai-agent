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
    app_env: str = "development"
    debug: bool = True
    allow_create_all: bool = True
    database_url: str = DEFAULT_DATABASE_URL
    chroma_host: str | None = None
    chroma_port: int = 8000
    chroma_persist_directory: str = str(BACKEND_DIR / "chroma_db")
    chroma_collection_name: str = "knowledge_chunks"
    knowledge_search_max_distance: float = 0.55
    reranker_enabled: bool = False
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_model_path: str | None = None
    reranker_candidate_k: int = 20
    reranker_batch_size: int = 16
    upload_directory: str = str(BACKEND_DIR / "uploads")
    max_upload_size: int = 5 * 1024 * 1024
    auth_enabled: bool = False
    public_engineer_registration_enabled: bool = False
    jwt_secret_key: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1200
    llm_json_mode: bool = True
    ollama_base_url: str = "http://localhost:11434"
    agent_runtime_enabled: bool = False

    def validate_runtime_security(self) -> None:
        """Validate demo/production security constraints."""

        strict_envs = {"demo", "production"}
        if self.app_env.lower() not in strict_envs:
            return

        if self.app_env.lower() == "production" and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true in production.")

        if (
            self.app_env.lower() == "production"
            and self.jwt_secret_key.get_secret_value() == "change-me-in-production"
        ):
            raise ValueError("JWT_SECRET_KEY must be configured in production.")

        if self.llm_provider.strip().lower() == "mock":
            raise ValueError("Mock LLM provider is not allowed in demo/production.")

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
