from pydantic import BaseModel, ValidationError

from app.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    StructuredModel,
)


class MockLLMProvider:
    """Network-free LLM provider for deterministic tests."""

    def __init__(
        self,
        response: BaseModel | dict | None = None,
        error: LLMProviderError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[list[LLMMessage]] = []

    def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        self.calls.append(messages)

        if self.error is not None:
            raise self.error

        try:
            if isinstance(self.response, response_model):
                return self.response

            return response_model.model_validate(self.response)
        except ValidationError as exc:
            raise LLMStructuredOutputError("LLM output failed schema validation.") from exc
