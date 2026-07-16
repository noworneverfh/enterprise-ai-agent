from collections.abc import Generator
from datetime import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import workflow  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.llm.base import LLMStructuredOutputError, LLMTimeoutError, LLMUnavailableError  # noqa: E402
from app.llm.factory import get_llm_provider  # noqa: E402
from app.llm.mock import MockLLMProvider  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolKnowledgeResult,
    ToolRuntimeData,
)


QUERY_STATUS = "\u67e5\u8be2 DEV-001 \u5f53\u524d\u72b6\u6001\u3002"
QUERY_KNOWLEDGE = "E101 \u62a5\u8b66\u4e00\u822c\u662f\u4ec0\u4e48\u539f\u56e0\uff1f"
QUERY_DIAGNOSIS = (
    "DEV-001 \u51fa\u73b0 E101 \u62a5\u8b66\u5e76\u6301\u7eed"
    "\u5347\u6e29\uff0c\u5e94\u8be5\u600e\u4e48\u5904\u7406\uff1f"
)
QUERY_HELLO = "\u4f60\u597d\u3002"


class ToolRecorder:
    def __init__(
        self,
        device_result: DeviceStatusToolResult | None = None,
        knowledge_result: KnowledgeSearchToolResult | None = None,
    ) -> None:
        self.device_result = device_result or _device_result(["high"])
        self.knowledge_result = knowledge_result or _knowledge_result()
        self.device_calls: list[DeviceStatusToolInput] = []
        self.knowledge_calls: list[KnowledgeSearchToolInput] = []

    def run_device(
        self,
        db: object,
        input_data: DeviceStatusToolInput,
    ) -> DeviceStatusToolResult:
        self.device_calls.append(input_data)
        return self.device_result

    def run_knowledge(
        self,
        input_data: KnowledgeSearchToolInput,
    ) -> KnowledgeSearchToolResult:
        self.knowledge_calls.append(input_data)
        return self.knowledge_result


@pytest.fixture
def agent_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[object, None, None]:
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: MockLLMProvider(response=_draft())

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_agent_api_device_status_query(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_STATUS})

    assert response.status_code == 200
    assert response.json()["device"]["device_code"] == "DEV-001"
    assert response.json()["tools_used"] == ["get_device_status"]
    assert len(recorder.device_calls) == 1
    assert recorder.knowledge_calls == []


def test_agent_api_knowledge_query(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_KNOWLEDGE})

    assert response.status_code == 200
    assert response.json()["sources"] == ["manual.md#chunk-0"]
    assert response.json()["tools_used"] == ["search_knowledge"]
    assert recorder.device_calls == []
    assert len(recorder.knowledge_calls) == 1


def test_agent_api_combined_diagnosis(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "high"
    assert data["device"]["device_code"] == "DEV-001"
    assert data["sources"] == ["manual.md#chunk-0"]
    assert data["tools_used"] == ["get_device_status", "search_knowledge"]
    assert len(recorder.device_calls) == 1
    assert len(recorder.knowledge_calls) == 1


def test_agent_api_small_talk_does_not_call_llm_or_tools(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)
    provider = MockLLMProvider(response=_draft())
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_HELLO})

    assert response.status_code == 200
    assert provider.calls == []
    assert recorder.device_calls == []
    assert recorder.knowledge_calls == []
    assert response.json()["risk_level"] == "unknown"


def test_agent_api_device_not_found_returns_200_with_warning(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, device_result=_device_not_found_result())

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    assert response.json()["device"] is None
    assert "Device not found." in response.json()["warnings"]


def test_agent_api_knowledge_no_results_returns_empty_sources(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        knowledge_result=KnowledgeSearchToolResult(
            ok=True,
            results=[],
            warnings=["No knowledge results found."],
        ),
    )

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_KNOWLEDGE})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "No knowledge results found." in response.json()["warnings"]


def test_agent_api_mock_provider_returns_complete_response(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    app.dependency_overrides[get_llm_provider] = lambda: MockLLMProvider(
        response=_draft(problem_summary="Provider summary.", risk_level="critical")
    )

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    data = response.json()
    assert data["problem_summary"] == "Provider summary."
    assert data["risk_level"] == "critical"
    assert data["disclaimer"]
    assert set(data) == {
        "problem_summary",
        "device",
        "device_status",
        "recent_alarms",
        "risk_level",
        "possible_causes",
        "recommended_actions",
        "sources",
        "tools_used",
        "warnings",
        "disclaimer",
    }


@pytest.mark.parametrize(
    "error",
    [
        LLMTimeoutError("timeout with sk-secret"),
        LLMUnavailableError("unavailable with https://provider.example"),
        LLMStructuredOutputError("bad output with stack trace"),
    ],
)
def test_agent_api_llm_errors_return_safe_fallback(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    _patch_tools(monkeypatch)
    app.dependency_overrides[get_llm_provider] = lambda: MockLLMProvider(error=error)

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    data = response.json()
    assert workflow.LLM_UNAVAILABLE_WARNING in data["warnings"]
    serialized = response.text
    assert "sk-secret" not in serialized
    assert "provider.example" not in serialized
    assert "stack trace" not in serialized


def test_agent_api_empty_query_returns_422(agent_client: TestClient) -> None:
    response = agent_client.post("/agent/diagnose", json={"query": "   "})

    assert response.status_code == 422


def test_agent_api_knowledge_top_k_out_of_range_returns_422(
    agent_client: TestClient,
) -> None:
    response = agent_client.post(
        "/agent/diagnose",
        json={"query": QUERY_KNOWLEDGE, "knowledge_top_k": 6},
    )

    assert response.status_code == 422


def test_agent_api_invalid_device_code_returns_422(agent_client: TestClient) -> None:
    response = agent_client.post(
        "/agent/diagnose",
        json={"query": QUERY_STATUS, "device_code": "bad"},
    )

    assert response.status_code == 422


def test_agent_api_invalid_llm_provider_config_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def override_get_db() -> Generator[object, None, None]:
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "llm_provider", "bad_provider")

    try:
        response = TestClient(app).post(
            "/agent/diagnose",
            json={"query": QUERY_HELLO},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM provider is not available."}


def test_agent_api_response_does_not_expose_internal_fields(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    serialized = response.text.lower()
    for forbidden in [
        "prompt",
        "context",
        "api_key",
        "base_url",
        "database_url",
        "file_path",
    ]:
        assert forbidden not in serialized


def test_agent_api_program_owned_fields_ignore_llm_freedom(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(
        monkeypatch,
        device_result=_device_result(["medium"], device_code="DEV-123"),
        knowledge_result=_knowledge_result(sources=["trusted.md#chunk-0"]),
    )
    app.dependency_overrides[get_llm_provider] = lambda: MockLLMProvider(
        response=_draft(problem_summary="LLM draft only.", risk_level="low")
    )

    response = agent_client.post(
        "/agent/diagnose",
        json={"query": "DEV-123 E101 \u62a5\u8b66"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["device"]["device_code"] == "DEV-123"
    assert data["sources"] == ["trusted.md#chunk-0"]
    assert data["tools_used"] == ["get_device_status", "search_knowledge"]
    assert data["problem_summary"] == "LLM draft only."


def test_agent_api_dependency_override_injects_provider(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    provider = MockLLMProvider(response=_draft(problem_summary="Injected provider."))
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    assert response.json()["problem_summary"] == "Injected provider."
    assert len(provider.calls) == 1


def _patch_tools(
    monkeypatch: pytest.MonkeyPatch,
    device_result: DeviceStatusToolResult | None = None,
    knowledge_result: KnowledgeSearchToolResult | None = None,
) -> ToolRecorder:
    recorder = ToolRecorder(
        device_result=device_result,
        knowledge_result=knowledge_result,
    )
    monkeypatch.setattr(workflow, "run_get_device_status_tool", recorder.run_device)
    monkeypatch.setattr(workflow, "run_search_knowledge_tool", recorder.run_knowledge)
    return recorder


def _draft(**overrides: object) -> dict:
    data = {
        "problem_summary": "Draft summary.",
        "risk_level": "medium",
        "possible_causes": ["Fan failure."],
        "recommended_actions": ["Stop high-load operation.", "Inspect fan."],
        "warnings": [],
    }
    data.update(overrides)
    return data


def _device_result(
    levels: list[str] | None = None,
    device_code: str = "DEV-001",
) -> DeviceStatusToolResult:
    now = datetime.utcnow()
    return DeviceStatusToolResult(
        ok=True,
        device_exists=True,
        device=ToolDeviceInfo(
            id=1,
            device_code=device_code,
            name="Demo Device",
            device_type="pump",
            location="Workshop A",
            is_online=True,
            created_at=now,
        ),
        latest_runtime_data=ToolRuntimeData(
            id=1,
            device_id=1,
            temperature=91.2,
            voltage=220.0,
            current=8.0,
            vibration=0.4,
            status="warning",
            recorded_at=now,
            created_at=now,
        ),
        recent_alarms=[
            ToolAlarmRecord(
                id=index + 1,
                device_id=1,
                alarm_code="E101",
                alarm_level=level,
                message=f"{level} alarm",
                is_resolved=False,
                occurred_at=now,
                resolved_at=None,
                created_at=now,
            )
            for index, level in enumerate(levels or [])
        ],
    )


def _device_not_found_result() -> DeviceStatusToolResult:
    return DeviceStatusToolResult(
        ok=True,
        device_exists=False,
        device=None,
        latest_runtime_data=None,
        recent_alarms=[],
        warnings=["Device not found."],
    )


def _knowledge_result(
    sources: list[str] | None = None,
) -> KnowledgeSearchToolResult:
    return KnowledgeSearchToolResult(
        ok=True,
        results=[
            ToolKnowledgeResult(
                chunk_id=index + 1,
                document_id=1,
                filename=f"manual-{index + 1}.md",
                chunk_index=index,
                content="E101 high temperature maintenance guidance.",
                source=source,
                distance=0.2 + index,
            )
            for index, source in enumerate(sources or ["manual.md#chunk-0"])
        ],
    )
