import json
import re
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.llm.base import (
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
    StructuredModel,
)


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MARKDOWN_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class OpenAICompatibleProvider:
    """OpenAI-compatible synchronous chat completion provider."""

    def __init__(
        self,
        api_key: SecretStr | str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        json_mode: bool = True,
        client: httpx.Client | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = (
            api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self._client = client
        self._sleep = sleep_func

    def __repr__(self) -> str:
        return (
            "OpenAICompatibleProvider("
            f"base_url={self.base_url!r}, "
            f"model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_retries={self.max_retries!r}, "
            f"temperature={self.temperature!r}, "
            f"max_tokens={self.max_tokens!r}, "
            f"json_mode={self.json_mode!r})"
        )

    def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        payload = self._build_payload(messages)
        response = self._post_with_retries(payload)
        content = self._extract_content(response)
        data = self._parse_json_content(content)

        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMStructuredOutputError(
                "LLM output failed schema validation."
            ) from exc

    def _build_payload(self, messages: list[LLMMessage]) -> dict:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        return payload

    def _post_with_retries(self, payload: dict) -> httpx.Response:
        total_attempts = 1 + self.max_retries
        last_error: Exception | None = None

        for attempt in range(total_attempts):
            try:
                response = self._client_or_default().post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": (
                            f"Bearer {self._api_key.get_secret_value()}"
                        ),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMTimeoutError("LLM request timed out.") from exc
            except httpx.TransportError as exc:
                last_error = exc
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMUnavailableError("LLM service is unavailable.") from exc

            if response.status_code < 400:
                return response

            if response.status_code in {401, 403}:
                raise LLMUnavailableError("LLM service authorization failed.")

            if response.status_code == 400:
                raise LLMProviderError("LLM provider rejected the request.")

            if response.status_code in RETRYABLE_STATUS_CODES:
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMUnavailableError("LLM service is unavailable.")

            raise LLMProviderError("LLM provider returned an error.")

        raise LLMUnavailableError("LLM service is unavailable.") from last_error

    def _client_or_default(self) -> httpx.Client:
        if self._client is not None:
            return self._client

        self._client = httpx.Client()
        return self._client

    def _extract_content(self, response: httpx.Response) -> str:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError("LLM response structure is invalid.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMStructuredOutputError("LLM response content is empty.")

        return content

    def _parse_json_content(self, content: str) -> dict:
        stripped = content.strip()
        match = MARKDOWN_JSON_PATTERN.match(stripped)
        if match is not None:
            stripped = match.group(1).strip()

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError("LLM response content is not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise LLMStructuredOutputError("LLM response JSON must be an object.")

        return parsed

    def _should_retry(self, attempt: int, total_attempts: int) -> bool:
        return attempt < total_attempts - 1

    def _sleep_before_retry(self, attempt: int) -> None:
        self._sleep(0.5 * (2**attempt))
