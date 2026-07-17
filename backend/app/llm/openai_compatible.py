import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAIToolCall:
    """Parsed OpenAI-compatible tool call request."""

    id: str | None
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class OpenAIToolCallingResponse:
    """Response shape consumed by AgentRuntime."""

    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None


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
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self._build_timeout(),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=0,
            ),
        )
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
        tools: list[dict[str, Any]] | None = None,
    ) -> StructuredModel:
        payload = self._build_payload(messages, tools=tools)
        response = self._post_with_retries(payload, self._client, mode="structured")

        content = self._extract_content(response)
        data = self._parse_json_content(content)

        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMStructuredOutputError(
                "LLM output failed schema validation."
            ) from exc

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> OpenAIToolCallingResponse:
        payload = self._build_tool_payload(messages, tools, tool_choice)
        response = self._post_with_retries(payload, self._client, mode="tool")
        message = self._extract_message(response)
        tool_calls = self.parse_tool_calls(response)

        if tool_calls:
            content = message.get("content")
            return OpenAIToolCallingResponse(
                content=content if isinstance(content, str) else None,
                tool_calls=tool_calls,
            )

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMStructuredOutputError("LLM response content is invalid.")

        return OpenAIToolCallingResponse(content=content, tool_calls=[])

    def parse_tool_calls(self, response: httpx.Response) -> list[OpenAIToolCall]:
        """Parse tool calls from an OpenAI-compatible chat completion response."""

        message = self._extract_message(response)
        tool_calls = message.get("tool_calls", [])
        if tool_calls is None:
            return []
        if not isinstance(tool_calls, list):
            raise LLMStructuredOutputError("LLM tool_calls must be a list.")

        parsed_calls: list[OpenAIToolCall] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                raise LLMStructuredOutputError("LLM tool_call structure is invalid.")

            function = tool_call.get("function")
            if not isinstance(function, dict):
                raise LLMStructuredOutputError("LLM tool_call function is invalid.")

            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise LLMStructuredOutputError("LLM tool_call function name is invalid.")

            raw_arguments = function.get("arguments", "{}")
            arguments = self._parse_tool_arguments(raw_arguments)

            call_id = tool_call.get("id")
            if call_id is not None and not isinstance(call_id, str):
                raise LLMStructuredOutputError("LLM tool_call id is invalid.")

            parsed_calls.append(
                OpenAIToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )

        return parsed_calls

    def _build_payload(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        if tools:
            payload["tools"] = tools

        return payload

    def _build_tool_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
        }

    def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            self._client.close()

    def _post_with_retries(
        self,
        payload: dict,
        client: httpx.Client,
        mode: str,
    ) -> httpx.Response:
        total_attempts = 1 + self.max_retries
        last_error: Exception | None = None

        for attempt in range(total_attempts):
            attempt_number = attempt + 1
            start_time = time.perf_counter()
            logger.info(
                "LLM request start: model=%s mode=%s attempt=%s",
                self.model,
                mode,
                attempt_number,
            )
            try:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": (
                            f"Bearer {self._api_key.get_secret_value()}"
                        ),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s exception_type=%s",
                    mode,
                    attempt_number,
                    type(exc).__name__,
                )
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMTimeoutError("LLM request timed out.") from exc
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s exception_type=%s",
                    mode,
                    attempt_number,
                    type(exc).__name__,
                )
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMUnavailableError("LLM service is unavailable.") from exc

            if response.status_code < 400:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    "LLM response success: model=%s mode=%s attempt=%s latency_ms=%s",
                    self.model,
                    mode,
                    attempt_number,
                    latency_ms,
                )
                return response

            self._log_http_error_response(response, mode, attempt_number)

            if response.status_code in {401, 403}:
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s status_code=%s",
                    mode,
                    attempt_number,
                    response.status_code,
                )
                raise LLMUnavailableError("LLM service authorization failed.")

            if response.status_code == 400:
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s status_code=%s",
                    mode,
                    attempt_number,
                    response.status_code,
                )
                raise LLMProviderError("LLM provider rejected the request.")

            if response.status_code in RETRYABLE_STATUS_CODES:
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s status_code=%s",
                    mode,
                    attempt_number,
                    response.status_code,
                )
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                raise LLMUnavailableError("LLM service is unavailable.")

            raise LLMProviderError("LLM provider returned an error.")

        raise LLMUnavailableError("LLM service is unavailable.") from last_error

    def _log_http_error_response(
        self,
        response: httpx.Response,
        mode: str,
        attempt_number: int,
    ) -> None:
        logger.warning(
            "LLM HTTP error response: mode=%s attempt=%s status_code=%s body_prefix=%s",
            mode,
            attempt_number,
            response.status_code,
            response.text[:500],
        )

    def _extract_content(self, response: httpx.Response) -> str:
        message = self._extract_message(response)
        try:
            content = message["content"]
        except KeyError as exc:
            raise LLMStructuredOutputError("LLM response structure is invalid.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMStructuredOutputError("LLM response content is empty.")

        return content

    def _extract_message(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError("LLM response structure is invalid.") from exc

        if not isinstance(message, dict):
            raise LLMStructuredOutputError("LLM response message is invalid.")

        return message

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

    def _parse_tool_arguments(self, raw_arguments: object) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments

        if not isinstance(raw_arguments, str):
            raise LLMStructuredOutputError("LLM tool_call arguments are invalid.")

        try:
            parsed = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError(
                "LLM tool_call arguments are not valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise LLMStructuredOutputError("LLM tool_call arguments must be an object.")

        return parsed

    def _should_retry(self, attempt: int, total_attempts: int) -> bool:
        return attempt < total_attempts - 1

    def _sleep_before_retry(self, attempt: int) -> None:
        self._sleep(0.5 * (2**attempt))

    def _build_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=min(10.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=min(10.0, self.timeout_seconds),
            pool=min(5.0, self.timeout_seconds),
        )
