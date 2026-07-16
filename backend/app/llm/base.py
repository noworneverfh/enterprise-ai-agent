from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class LLMMessage(BaseModel):
    """Message passed to an LLM provider."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMProviderError(Exception):
    """Base exception for LLM provider failures."""


class LLMUnavailableError(LLMProviderError):
    """Raised when the configured LLM service is unavailable."""


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM call times out."""


class LLMStructuredOutputError(LLMProviderError):
    """Raised when LLM output cannot satisfy the expected schema."""


class LLMProvider(Protocol):
    """Provider interface for structured LLM completion."""

    def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        """Return a response validated by response_model."""
