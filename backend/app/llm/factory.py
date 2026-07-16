from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


class LLMProviderConfigurationError(Exception):
    """Raised when the configured LLM provider cannot be initialized."""


def get_llm_provider() -> LLMProvider:
    """Create the configured LLM provider."""

    provider_name = settings.llm_provider.strip().lower()

    if provider_name == "mock":
        return MockLLMProvider(
            response={
                "problem_summary": "Mock diagnosis draft generated from tool context.",
                "risk_level": "unknown",
                "possible_causes": [],
                "recommended_actions": [
                    "Please combine equipment data and maintenance documents for on-site inspection."
                ],
                "warnings": ["Mock LLM provider is active."],
            }
        )

    if provider_name == "openai_compatible":
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

    raise LLMProviderConfigurationError(
        f"Unsupported LLM provider configured: {settings.llm_provider}"
    )
