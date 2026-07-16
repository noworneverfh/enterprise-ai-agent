import json
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.llm.base import (  # noqa: E402
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.factory import LLMProviderConfigurationError, get_llm_provider  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from app.schemas.agent import AgentDiagnosisDraft  # noqa: E402


def test_openai_compatible_accepts_plain_json_response() -> None:
    provider, _ = _provider_with_responses([_chat_response(_draft_json())])

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "E101 temperature alarm."
    assert result.risk_level == "high"


def test_openai_compatible_accepts_markdown_json_code_block() -> None:
    provider, _ = _provider_with_responses(
        [_chat_response(f"```json\n{_draft_json()}\n```")]
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.recommended_actions == ["Stop high-load operation."]


def test_openai_compatible_rejects_invalid_json_content() -> None:
    provider, _ = _provider_with_responses([_chat_response("{bad json")])

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_openai_compatible_rejects_schema_invalid_content() -> None:
    provider, _ = _provider_with_responses(
        [_chat_response('{"problem_summary": "", "risk_level": "bad"}')]
    )

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_openai_compatible_rejects_missing_choices() -> None:
    provider, _ = _provider_with_responses([httpx.Response(200, json={})])

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_openai_compatible_rejects_missing_content() -> None:
    provider, _ = _provider_with_responses(
        [httpx.Response(200, json={"choices": [{"message": {}}]})]
    )

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_openai_compatible_timeout_maps_to_timeout_error() -> None:
    provider, calls = _provider_with_responses(
        [httpx.TimeoutException("timeout")],
        max_retries=0,
    )

    with pytest.raises(LLMTimeoutError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 1


def test_openai_compatible_network_failure_retries_then_succeeds() -> None:
    provider, calls = _provider_with_responses(
        [httpx.ConnectError("network down"), _chat_response(_draft_json())],
        max_retries=1,
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.risk_level == "high"
    assert len(calls["requests"]) == 2
    assert calls["sleeps"] == [0.5]


def test_openai_compatible_429_retries_then_succeeds() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(429), _chat_response(_draft_json())],
        max_retries=1,
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "E101 temperature alarm."
    assert len(calls["requests"]) == 2


def test_openai_compatible_500_retry_exhaustion() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(500), httpx.Response(500), httpx.Response(500)],
        max_retries=2,
    )

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 3
    assert calls["sleeps"] == [0.5, 1.0]


def test_openai_compatible_401_does_not_retry() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(401), _chat_response(_draft_json())],
        max_retries=2,
    )

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 1
    assert calls["sleeps"] == []


def test_openai_compatible_400_does_not_retry() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(400), _chat_response(_draft_json())],
        max_retries=2,
    )

    with pytest.raises(LLMProviderError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 1
    assert calls["sleeps"] == []


def test_openai_compatible_max_attempts_are_respected() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(503), httpx.Response(503), httpx.Response(503)],
        max_retries=2,
    )

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 3


def test_openai_compatible_json_mode_sends_response_format() -> None:
    provider, calls = _provider_with_responses(
        [_chat_response(_draft_json())],
        json_mode=True,
    )

    provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert calls["json_payloads"][0]["response_format"] == {"type": "json_object"}


def test_openai_compatible_json_mode_false_omits_response_format() -> None:
    provider, calls = _provider_with_responses(
        [_chat_response(_draft_json())],
        json_mode=False,
    )

    provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert "response_format" not in calls["json_payloads"][0]


def test_openai_compatible_sends_authorization_header_and_strips_base_url() -> None:
    provider, calls = _provider_with_responses([_chat_response(_draft_json())])

    provider.complete_structured(_messages(), AgentDiagnosisDraft)

    request = calls["requests"][0]
    assert request.headers["Authorization"] == "Bearer test-secret-key"
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"


def test_openai_compatible_repr_and_exceptions_do_not_leak_api_key() -> None:
    provider, _ = _provider_with_responses(
        [httpx.Response(401)],
        api_key="very-secret-key",
    )

    assert "very-secret-key" not in repr(provider)

    with pytest.raises(LLMUnavailableError) as exc_info:
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert "very-secret-key" not in str(exc_info.value)


def test_factory_creates_openai_compatible_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1/")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    provider = get_llm_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://llm.example.test/v1"
    assert provider.model == "demo-model"


def test_factory_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    with pytest.raises(LLMProviderConfigurationError, match="API key"):
        get_llm_provider()


def test_factory_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    with pytest.raises(LLMProviderConfigurationError, match="base URL"):
        get_llm_provider()


def test_factory_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(settings, "llm_model", "")

    with pytest.raises(LLMProviderConfigurationError, match="model"):
        get_llm_provider()


def _provider_with_responses(
    responses: list[httpx.Response | Exception],
    max_retries: int = 2,
    json_mode: bool = True,
    api_key: str = "test-secret-key",
) -> tuple[OpenAICompatibleProvider, dict]:
    calls: dict = {"requests": [], "json_payloads": [], "sleeps": []}
    queued = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["requests"].append(request)
        calls["json_payloads"].append(json.loads(request.content.decode("utf-8")))
        item = queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def sleep(seconds: float) -> None:
        calls["sleeps"].append(seconds)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        base_url="https://llm.example.test/v1/",
        model="demo-model",
        timeout_seconds=3,
        max_retries=max_retries,
        temperature=0.2,
        max_tokens=1200,
        json_mode=json_mode,
        client=client,
        sleep_func=sleep,
    )

    return provider, calls


def _messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Return JSON."),
        LLMMessage(role="user", content="Diagnose E101."),
    ]


def _draft_json() -> str:
    return json.dumps(
        {
            "problem_summary": "E101 temperature alarm.",
            "risk_level": "high",
            "possible_causes": ["Fan failure."],
            "recommended_actions": ["Stop high-load operation."],
            "warnings": [],
        }
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )
