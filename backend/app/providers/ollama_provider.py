from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
    StructuredModel,
)


logger = logging.getLogger(__name__)
MARKDOWN_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class OllamaProvider:
    """Structured LLM provider backed by a local Ollama server."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 60,
        temperature: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def __repr__(self) -> str:
        return (
            "OllamaProvider("
            f"base_url={self.base_url!r}, "
            f"model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"temperature={self.temperature!r})"
        )

    def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
        }

        try:
            response = self._client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("Ollama request timed out.") from exc
        except httpx.TransportError as exc:
            raise LLMUnavailableError("Ollama service is unavailable.") from exc

        if response.status_code >= 500:
            logger.warning("Ollama request failed: status_code=%s", response.status_code)
            raise LLMUnavailableError("Ollama service is unavailable.")
        if response.status_code >= 400:
            logger.warning("Ollama rejected request: status_code=%s", response.status_code)
            raise LLMProviderError("Ollama provider rejected the request.")

        content = self._extract_content(response)
        data = self._parse_json_content(content)
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMStructuredOutputError(
                "Ollama output failed schema validation."
            ) from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _extract_content(self, response: httpx.Response) -> str:
        try:
            body = response.json()
            message = body["message"]
            content = message["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMStructuredOutputError("Ollama response structure is invalid.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMStructuredOutputError("Ollama response content is empty.")

        return content

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        match = MARKDOWN_JSON_PATTERN.match(stripped)
        if match is not None:
            stripped = match.group(1).strip()

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError("Ollama response content is not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise LLMStructuredOutputError("Ollama response JSON must be an object.")
        return parsed
