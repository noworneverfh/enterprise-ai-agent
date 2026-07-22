from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.ollama_provider import OllamaProvider


class LLMProviderConfigurationError(Exception):
    """Raised when the configured LLM provider cannot be initialized."""


_cached_provider: LLMProvider | None = None
_cached_provider_key: tuple | None = None


def get_llm_provider() -> LLMProvider:
    """Return the application-level configured LLM provider singleton."""

    global _cached_provider, _cached_provider_key

    provider_key = _build_provider_cache_key()
    if _cached_provider is not None and _cached_provider_key == provider_key:
        return _cached_provider

    close_llm_provider()
    _cached_provider = _create_llm_provider()
    _cached_provider_key = provider_key
    return _cached_provider


def close_llm_provider() -> None:
    """Close and clear the cached LLM provider, if it owns resources."""

    global _cached_provider, _cached_provider_key

    if _cached_provider is not None:
        close = getattr(_cached_provider, "close", None)
        if callable(close):
            close()

    _cached_provider = None
    _cached_provider_key = None


def _create_llm_provider() -> LLMProvider:
    provider_name = settings.llm_provider.strip().lower()

    if provider_name == "mock":
        return MockLLMProvider(
            response={
                "problem_summary": "系统已根据设备运行数据、报警记录和维修资料生成辅助诊断结果，请结合现场情况确认。",
                "risk_level": "unknown",
                "possible_causes": [],
                "recommended_actions": [
                    "建议现场检查设备运行状态，并结合维修手册确认异常原因。"
                ],
                "warnings": ["当前使用本地模拟模型，仅用于开发和测试环境。"],
            }
        )

    if provider_name in {"openai", "openai_compatible"}:
        if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
            raise LLMProviderConfigurationError("LLM API key is required.")

        if settings.llm_base_url is None or not settings.llm_base_url.strip():
            raise LLMProviderConfigurationError("LLM base URL is required.")

        if settings.llm_model is None or not settings.llm_model.strip():
            raise LLMProviderConfigurationError("LLM model is required.")

        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            json_mode=settings.llm_json_mode,
        )

    if provider_name == "ollama":
        if settings.llm_model is None or not settings.llm_model.strip():
            raise LLMProviderConfigurationError("LLM model is required.")

        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    raise LLMProviderConfigurationError(
        f"Unsupported LLM provider configured: {settings.llm_provider}"
    )


def _build_provider_cache_key() -> tuple:
    api_key = (
        settings.llm_api_key.get_secret_value()
        if settings.llm_api_key is not None
        else None
    )
    return (
        settings.llm_provider,
        api_key,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout_seconds,
        settings.llm_max_retries,
        settings.llm_temperature,
        settings.llm_max_tokens,
        settings.llm_json_mode,
        settings.ollama_base_url,
    )
