from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider


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

    raise LLMProviderConfigurationError(
        f"Unsupported LLM provider configured: {settings.llm_provider}"
    )
