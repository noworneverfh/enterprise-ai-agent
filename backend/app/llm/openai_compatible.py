import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

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
        self.last_call_metadata: dict[str, Any] | None = None
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
                    "LLM request failed: mode=%s attempt=%s exception_type=%s "
                    "payload=%s",
                    mode,
                    attempt_number,
                    type(exc).__name__,
                    self._safe_payload_summary(payload),
                )
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                self._record_failure_metadata(
                    mode=mode,
                    attempt_number=attempt_number,
                    error_type=type(exc).__name__,
                )
                raise LLMTimeoutError("LLM request timed out.") from exc
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s exception_type=%s "
                    "payload=%s",
                    mode,
                    attempt_number,
                    type(exc).__name__,
                    self._safe_payload_summary(payload),
                )
                if self._should_retry(attempt, total_attempts):
                    self._sleep_before_retry(attempt)
                    continue
                self._record_failure_metadata(
                    mode=mode,
                    attempt_number=attempt_number,
                    error_type=type(exc).__name__,
                )
                raise LLMUnavailableError("LLM service is unavailable.") from exc

            if response.status_code < 400:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                metadata = self._record_success_metadata(
                    response=response,
                    mode=mode,
                    attempt_number=attempt_number,
                    latency_ms=latency_ms,
                )
                logger.info(
                    "LLM response success: provider=openai_compatible model=%s "
                    "mode=%s attempt=%s latency_ms=%s response_id=%s "
                    "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    self.model,
                    mode,
                    attempt_number,
                    latency_ms,
                    metadata.get("response_id"),
                    metadata.get("prompt_tokens"),
                    metadata.get("completion_tokens"),
                    metadata.get("total_tokens"),
                )
                return response

            self._log_http_error_response(response, mode, attempt_number, payload)

            if response.status_code in {401, 403}:
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s status_code=%s",
                    mode,
                    attempt_number,
                    response.status_code,
                )
                self._record_failure_metadata(
                    mode=mode,
                    attempt_number=attempt_number,
                    error_type=f"HTTP_{response.status_code}",
                )
                raise LLMUnavailableError("LLM service authorization failed.")

            if response.status_code == 400:
                logger.warning(
                    "LLM request failed: mode=%s attempt=%s status_code=%s",
                    mode,
                    attempt_number,
                    response.status_code,
                )
                self._record_failure_metadata(
                    mode=mode,
                    attempt_number=attempt_number,
                    error_type="HTTP_400",
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
                self._record_failure_metadata(
                    mode=mode,
                    attempt_number=attempt_number,
                    error_type=f"HTTP_{response.status_code}",
                )
                raise LLMUnavailableError("LLM service is unavailable.")

            self._record_failure_metadata(
                mode=mode,
                attempt_number=attempt_number,
                error_type=f"HTTP_{response.status_code}",
            )
            raise LLMProviderError("LLM provider returned an error.")

        raise LLMUnavailableError("LLM service is unavailable.") from last_error

    def _record_success_metadata(
        self,
        *,
        response: httpx.Response,
        mode: str,
        attempt_number: int,
        latency_ms: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        metadata = {
            "request_id": str(uuid4()),
            "provider": "openai_compatible",
            "model": self.model,
            "base_url_domain": self.base_url.replace("https://", "").replace("http://", "").split("/")[0],
            "mode": mode,
            "generation_mode": "real",
            "fallback_occurred": False,
            "attempt": attempt_number,
            "latency_ms": latency_ms,
            "response_id": body.get("id"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.last_call_metadata = metadata
        return metadata

    def _record_failure_metadata(
        self,
        *,
        mode: str,
        attempt_number: int,
        error_type: str,
    ) -> dict[str, Any]:
        metadata = {
            "request_id": str(uuid4()),
            "provider": "openai_compatible",
            "model": self.model,
            "base_url_domain": self.base_url.replace("https://", "").replace("http://", "").split("/")[0],
            "mode": mode,
            "generation_mode": "real",
            "fallback_occurred": False,
            "attempt": attempt_number,
            "latency_ms": None,
            "response_id": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "status": "failed",
            "error_type": error_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.last_call_metadata = metadata
        return metadata

    def _log_http_error_response(
        self,
        response: httpx.Response,
        mode: str,
        attempt_number: int,
        payload: dict,
    ) -> None:
        logger.warning(
            "LLM HTTP error response: mode=%s attempt=%s status_code=%s "
            "body_prefix=%s payload=%s",
            mode,
            attempt_number,
            response.status_code,
            response.text[:500],
            self._safe_payload_summary(payload),
        )

    def _safe_payload_summary(self, payload: object) -> dict[str, Any]:
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = json.loads(payload.decode("utf-8"))
            except Exception:
                payload = {}

        if not isinstance(payload, dict):
            payload = {}

        messages = payload.get("messages")
        message_list = messages if isinstance(messages, list) else []
        tools = payload.get("tools")
        tool_list = tools if isinstance(tools, list) else []

        return {
            "url": f"{self.base_url}/chat/completions",
            "model": payload.get("model", self.model),
            "messages_count": len(message_list),
            "messages_last_three": [
                self._safe_message_structure(message)
                for message in message_list[-3:]
                if isinstance(message, dict)
            ],
            "tools": [
                tool.get("function", {}).get("name")
                for tool in tool_list
                if isinstance(tool.get("function"), dict)
            ],
            "tool_choice": payload.get("tool_choice"),
        }

    def _safe_message_structure(self, message: dict[str, Any]) -> dict[str, Any]:
        tool_calls = message.get("tool_calls")
        return {
            "role": message.get("role"),
            "tool_call_id": message.get("tool_call_id"),
            "name": message.get("name"),
            "content_type": type(message.get("content")).__name__,
            "tool_calls": (
                [
                    {
                        "id": tool_call.get("id"),
                        "name": (
                            tool_call.get("function", {}).get("name")
                            if isinstance(tool_call.get("function"), dict)
                            else None
                        ),
                    }
                    for tool_call in tool_calls
                    if isinstance(tool_call, dict)
                ]
                if isinstance(tool_calls, list)
                else None
            ),
        }

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
