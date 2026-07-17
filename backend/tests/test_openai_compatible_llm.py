import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import BACKEND_DIR as CONFIG_BACKEND_DIR  # noqa: E402
from app.core.config import Settings, settings  # noqa: E402
from app.agent.tool_registry import list_openai_tool_schemas  # noqa: E402
from app.llm.base import (  # noqa: E402
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.factory import (  # noqa: E402
    LLMProviderConfigurationError,
    close_llm_provider,
    get_llm_provider,
)
from app.llm import openai_compatible as openai_compatible_module  # noqa: E402
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


def test_openai_compatible_connect_error_retry_exhaustion() -> None:
    provider, calls = _provider_with_responses(
        [
            httpx.ConnectError("network down"),
            httpx.ConnectError("network down"),
            httpx.ConnectError("network down"),
        ],
        max_retries=2,
    )

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 3
    assert calls["sleeps"] == [0.5, 1.0]


def test_openai_compatible_read_timeout_retries_then_succeeds() -> None:
    provider, calls = _provider_with_responses(
        [httpx.ReadTimeout("read timeout"), _chat_response(_draft_json())],
        max_retries=1,
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.risk_level == "high"
    assert len(calls["requests"]) == 2
    assert calls["sleeps"] == [0.5]


def test_openai_compatible_remote_protocol_error_retries_then_succeeds() -> None:
    provider, calls = _provider_with_responses(
        [
            httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
            _chat_response(_draft_json()),
        ],
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


def test_openai_compatible_remote_protocol_error_retry_exhaustion() -> None:
    provider, calls = _provider_with_responses(
        [
            httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
            httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
        ],
        max_retries=1,
    )

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert len(calls["requests"]) == 2
    assert calls["sleeps"] == [0.5]


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


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, LLMProviderError),
        (403, LLMUnavailableError),
    ],
)
def test_openai_compatible_http_error_logs_safe_response_body(
    caplog: pytest.LogCaptureFixture,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    secret_key = "sk-secret-should-not-appear"
    secret_prompt = "secret user prompt should not appear"
    body = {
        "error": {
            "code": "ProviderError",
            "message": "visible provider error body",
            "debug": "x" * 600,
        }
    }
    provider, _ = _provider_with_responses(
        [httpx.Response(status_code, json=body)],
        api_key=secret_key,
    )

    caplog.set_level("WARNING")
    with pytest.raises(expected_error):
        provider.complete_structured(
            [LLMMessage(role="user", content=secret_prompt)],
            AgentDiagnosisDraft,
        )

    log_text = caplog.text
    assert "LLM HTTP error response" in log_text
    assert "mode=structured" in log_text
    assert f"status_code={status_code}" in log_text
    assert "visible provider error body" in log_text
    assert secret_key not in log_text
    assert secret_prompt not in log_text


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


def test_openai_compatible_payload_includes_tools() -> None:
    provider, calls = _provider_with_responses([_chat_response(_draft_json())])
    tools = list_openai_tool_schemas()

    provider.complete_structured(_messages(), AgentDiagnosisDraft, tools=tools)

    assert calls["json_payloads"][0]["tools"] == tools
    assert calls["json_payloads"][0]["tools"][0]["function"]["name"] == (
        "get_device_status"
    )


def test_openai_compatible_complete_with_tools_payload_includes_tools_and_auto_choice() -> None:
    provider, calls = _provider_with_responses(
        [_chat_response("Final answer from model.")]
    )
    tools = list_openai_tool_schemas()

    result = provider.complete_with_tools(_tool_messages(), tools)

    assert result.content == "Final answer from model."
    assert result.tool_calls == []
    payload = calls["json_payloads"][0]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert "response_format" not in payload


def test_openai_compatible_complete_with_tools_accepts_forced_tool_choice() -> None:
    provider, calls = _provider_with_responses(
        [_chat_response("Final answer from model.")]
    )
    forced_choice = {
        "type": "function",
        "function": {"name": "get_device_status"},
    }

    provider.complete_with_tools(
        _tool_messages(),
        list_openai_tool_schemas(),
        tool_choice=forced_choice,
    )

    assert calls["json_payloads"][0]["tool_choice"] == forced_choice


def test_openai_compatible_complete_with_tools_parses_tool_calls() -> None:
    provider, calls = _provider_with_responses(
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_device_status",
                                            "arguments": json.dumps(
                                                {
                                                    "device_code": "DEV-001",
                                                    "alarm_limit": 5,
                                                }
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        ]
    )

    result = provider.complete_with_tools(_tool_messages(), list_openai_tool_schemas())

    assert len(calls["requests"]) == 1
    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "get_device_status"
    assert result.tool_calls[0].arguments == {
        "device_code": "DEV-001",
        "alarm_limit": 5,
    }


def test_openai_compatible_complete_with_tools_retries_then_succeeds() -> None:
    provider, calls = _provider_with_responses(
        [httpx.Response(500), _chat_response("Final answer after retry.")],
        max_retries=1,
    )

    result = provider.complete_with_tools(_tool_messages(), list_openai_tool_schemas())

    assert result.content == "Final answer after retry."
    assert result.tool_calls == []
    assert len(calls["requests"]) == 2
    assert calls["sleeps"] == [0.5]


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


def test_openai_compatible_owned_client_is_closed_by_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[FakeContextClient] = []

    def client_factory(*args: object, **kwargs: object) -> FakeContextClient:
        client = FakeContextClient([_chat_response(_draft_json())])
        created_clients.append(client)
        return client

    monkeypatch.setattr(openai_compatible_module.httpx, "Client", client_factory)
    provider = OpenAICompatibleProvider(
        api_key="test-secret-key",
        base_url="https://llm.example.test/v1",
        model="demo-model",
    )

    assert len(created_clients) == 1
    assert created_clients[0].entered is False
    assert created_clients[0].closed is False

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "E101 temperature alarm."
    assert created_clients[0].closed is False

    provider.close()

    assert created_clients[0].closed is True


def test_openai_compatible_external_client_is_not_closed() -> None:
    client = FakeContextClient([_chat_response(_draft_json())])
    provider = OpenAICompatibleProvider(
        api_key="test-secret-key",
        base_url="https://llm.example.test/v1",
        model="demo-model",
        client=client,  # type: ignore[arg-type]
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.risk_level == "high"
    assert client.entered is False
    assert client.closed is False

    provider.close()

    assert client.closed is False


def test_openai_compatible_reuses_owned_client_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[FakeContextClient] = []

    def client_factory(*args: object, **kwargs: object) -> FakeContextClient:
        client = FakeContextClient(
            [_chat_response(_draft_json()), _chat_response(_draft_json())]
        )
        created_clients.append(client)
        return client

    monkeypatch.setattr(openai_compatible_module.httpx, "Client", client_factory)
    provider = OpenAICompatibleProvider(
        api_key="test-secret-key",
        base_url="https://llm.example.test/v1",
        model="demo-model",
    )

    first = provider.complete_structured(_messages(), AgentDiagnosisDraft)
    second = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert first.risk_level == "high"
    assert second.risk_level == "high"
    assert len(created_clients) == 1
    assert created_clients[0].post_count == 2
    assert created_clients[0].closed is False

    provider.close()

    assert created_clients[0].closed is True


def test_openai_compatible_retry_reuses_same_internal_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[FakeContextClient] = []

    def client_factory(*args: object, **kwargs: object) -> FakeContextClient:
        client = FakeContextClient([httpx.Response(500), _chat_response(_draft_json())])
        created_clients.append(client)
        return client

    monkeypatch.setattr(openai_compatible_module.httpx, "Client", client_factory)
    sleeps: list[float] = []
    provider = OpenAICompatibleProvider(
        api_key="test-secret-key",
        base_url="https://llm.example.test/v1",
        model="demo-model",
        max_retries=1,
        sleep_func=sleeps.append,
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "E101 temperature alarm."
    assert len(created_clients) == 1
    assert created_clients[0].post_count == 2
    assert created_clients[0].closed is False
    assert sleeps == [0.5]

    provider.close()

    assert created_clients[0].closed is True


def test_openai_compatible_internal_client_uses_stability_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    created_clients: list[FakeContextClient] = []

    def client_factory(*args: object, **kwargs: object) -> FakeContextClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        client = FakeContextClient([_chat_response(_draft_json())])
        created_clients.append(client)
        return client

    monkeypatch.setattr(openai_compatible_module.httpx, "Client", client_factory)
    provider = OpenAICompatibleProvider(
        api_key="test-secret-key",
        base_url="https://llm.example.test/v1",
        model="demo-model",
        timeout_seconds=30,
    )

    timeout = captured["kwargs"]["timeout"]
    limits = captured["kwargs"]["limits"]
    assert timeout.connect == 10.0
    assert timeout.read == 30
    assert timeout.write == 10.0
    assert timeout.pool == 5.0
    assert limits.max_connections == 20
    assert limits.max_keepalive_connections == 0
    assert len(created_clients) == 1

    provider.close()


def test_openai_compatible_parses_tool_calls_json_arguments() -> None:
    provider, _ = _provider_with_responses([])
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_device_status",
                                    "arguments": json.dumps(
                                        {
                                            "device_code": "DEV-001",
                                            "alarm_limit": 3,
                                        }
                                    ),
                                },
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {
                                    "name": "search_knowledge",
                                    "arguments": '{"query": "E203报警", "top_k": 5}',
                                },
                            },
                        ],
                    }
                }
            ]
        },
    )

    calls = provider.parse_tool_calls(response)

    assert calls[0].id == "call_1"
    assert calls[0].name == "get_device_status"
    assert calls[0].arguments == {"device_code": "DEV-001", "alarm_limit": 3}
    assert calls[1].id == "call_2"
    assert calls[1].name == "search_knowledge"
    assert calls[1].arguments == {"query": "E203报警", "top_k": 5}


def test_openai_compatible_parses_empty_tool_calls() -> None:
    provider, _ = _provider_with_responses([])

    assert provider.parse_tool_calls(_chat_response(_draft_json())) == []


def test_openai_compatible_rejects_invalid_tool_call_arguments() -> None:
    provider, _ = _provider_with_responses([])
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search_knowledge",
                                    "arguments": "{bad json",
                                },
                            }
                        ]
                    }
                }
            ]
        },
    )

    with pytest.raises(LLMStructuredOutputError):
        provider.parse_tool_calls(response)


def test_factory_creates_openai_compatible_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    close_llm_provider()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1/")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    try:
        provider = get_llm_provider()

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://llm.example.test/v1"
        assert provider.model == "demo-model"
    finally:
        close_llm_provider()


def test_factory_reuses_same_provider_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    close_llm_provider()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1/")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    try:
        first = get_llm_provider()
        second = get_llm_provider()

        assert first is second
        assert isinstance(first, OpenAICompatibleProvider)
        assert first._client is second._client
    finally:
        close_llm_provider()


def test_factory_close_releases_cached_provider_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_llm_provider()
    created_clients: list[FakeContextClient] = []

    def client_factory(*args: object, **kwargs: object) -> FakeContextClient:
        client = FakeContextClient([])
        created_clients.append(client)
        return client

    monkeypatch.setattr(openai_compatible_module.httpx, "Client", client_factory)
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1/")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    provider = get_llm_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert len(created_clients) == 1
    assert created_clients[0].closed is False

    close_llm_provider()

    assert created_clients[0].closed is True


def test_factory_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    close_llm_provider()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    with pytest.raises(LLMProviderConfigurationError, match="API key"):
        get_llm_provider()
    close_llm_provider()


def test_factory_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    close_llm_provider()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "demo-model")

    with pytest.raises(LLMProviderConfigurationError, match="base URL"):
        get_llm_provider()
    close_llm_provider()


def test_factory_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    close_llm_provider()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("factory-secret"))
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(settings, "llm_model", "")

    with pytest.raises(LLMProviderConfigurationError, match="model"):
        get_llm_provider()
    close_llm_provider()


def test_settings_env_file_is_fixed_to_backend_env() -> None:
    assert Path(Settings.model_config["env_file"]) == CONFIG_BACKEND_DIR / ".env"
    assert Settings.model_config["env_file_encoding"] == "utf-8"


def test_settings_env_file_same_from_project_root_and_backend_cwd() -> None:
    root_output = _read_env_file_from_cwd(Path(__file__).resolve().parents[1].parent)
    backend_output = _read_env_file_from_cwd(CONFIG_BACKEND_DIR)
    expected = str((CONFIG_BACKEND_DIR / ".env").resolve())

    assert root_output == expected
    assert backend_output == expected


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


class FakeContextClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.entered = False
        self.closed = False
        self.post_count = 0

    def __enter__(self) -> "FakeContextClient":
        self.entered = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True

    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        self.post_count += 1
        return self.responses.pop(0)


def _read_env_file_from_cwd(cwd: Path) -> str:
    if cwd == CONFIG_BACKEND_DIR:
        path_setup = "sys.path.insert(0, str(Path('.').resolve()))"
        python_exe = str((cwd.parent / ".venv" / "Scripts" / "python.exe").resolve())
    else:
        path_setup = "sys.path.insert(0, str(Path('backend').resolve()))"
        python_exe = str((cwd / ".venv" / "Scripts" / "python.exe").resolve())

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        f"{path_setup}\n"
        "from app.core.config import Settings\n"
        "print(Path(Settings.model_config['env_file']).resolve())\n"
    )
    result = subprocess.run(
        [python_exe, "-c", script],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Return JSON."),
        LLMMessage(role="user", content="Diagnose E101."),
    ]


def _tool_messages() -> list[dict]:
    return [
        {"role": "system", "content": "Use tools when needed."},
        {"role": "user", "content": "Query DEV-001 status."},
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
