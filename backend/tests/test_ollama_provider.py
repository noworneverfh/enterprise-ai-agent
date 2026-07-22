import json
import sys
from pathlib import Path

import httpx
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.llm.base import (  # noqa: E402
    LLMMessage,
    LLMProviderError,
    LLMStructuredOutputError,
    LLMUnavailableError,
)
from app.providers.ollama_provider import OllamaProvider  # noqa: E402
from app.schemas.agent import AgentDiagnosisDraft  # noqa: E402


def test_ollama_provider_returns_structured_model() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "problem_summary": "Local model diagnosis.",
                            "risk_level": "medium",
                            "possible_causes": ["Motor load is elevated."],
                            "recommended_actions": ["Inspect the motor load."],
                            "warnings": [],
                        }
                    )
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://ollama.test",
        model="qwen2.5",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.complete_structured(_messages(), AgentDiagnosisDraft)

    assert result.problem_summary == "Local model diagnosis."
    assert result.risk_level == "medium"
    assert calls[0]["model"] == "qwen2.5"
    assert calls[0]["format"] == "json"
    assert calls[0]["stream"] is False


def test_ollama_provider_rejects_invalid_json() -> None:
    provider = _provider_with_response(httpx.Response(200, json={"message": {"content": "not-json"}}))

    with pytest.raises(LLMStructuredOutputError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_ollama_provider_maps_500_to_unavailable() -> None:
    provider = _provider_with_response(httpx.Response(500, json={"error": "down"}))

    with pytest.raises(LLMUnavailableError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def test_ollama_provider_maps_400_to_provider_error() -> None:
    provider = _provider_with_response(httpx.Response(400, json={"error": "bad"}))

    with pytest.raises(LLMProviderError):
        provider.complete_structured(_messages(), AgentDiagnosisDraft)


def _provider_with_response(response: httpx.Response) -> OllamaProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return OllamaProvider(
        base_url="http://ollama.test",
        model="qwen3",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Return JSON."),
        LLMMessage(role="user", content="Diagnose E203."),
    ]
