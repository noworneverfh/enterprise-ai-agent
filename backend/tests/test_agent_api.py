from collections.abc import Generator
from datetime import datetime
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import runtime as runtime_module  # noqa: E402
from app.agent import workflow  # noqa: E402
from app.agent.runtime import AgentRuntimeLLMResponse, AgentRuntimeToolCall  # noqa: E402
from app.conversation import service as conversation_service  # noqa: E402
from app.conversation.schemas import ConversationCreate, MessageCreate  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.llm.base import LLMStructuredOutputError, LLMTimeoutError, LLMUnavailableError  # noqa: E402
from app.llm.factory import get_llm_provider  # noqa: E402
from app.llm.mock import MockLLMProvider  # noqa: E402
from app.main import app  # noqa: E402
from app.models.diagnosis import DiagnosisReport, DiagnosisTrace  # noqa: E402
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

    monkeypatch.setattr(settings, "agent_runtime_enabled", False)
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


def test_agent_api_report_v2_is_available_by_explicit_version_header(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    app.dependency_overrides[get_llm_provider] = lambda: MockLLMProvider(
        response=_draft(problem_summary="Provider summary.", risk_level="critical")
    )

    response = agent_client.post(
        "/agent/diagnose",
        json={"query": QUERY_DIAGNOSIS},
        headers={"X-Report-Version": "2.0"},
    )

    assert response.status_code == 200
    report = response.json()["report_v2"]
    assert report["report_version"] == "2.0"
    assert report["generation_mode"] == "mock"
    assert report["confirmed_facts"]
    assert report["risk"]["level"] == "critical"


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


def test_agent_api_runtime_disabled_keeps_legacy_workflow(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_runtime_enabled", False)
    recorder = _patch_tools(monkeypatch)
    provider = MockLLMProvider(response=_draft())
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    assert response.json()["tools_used"] == ["get_device_status", "search_knowledge"]
    assert len(provider.calls) == 1
    assert len(recorder.device_calls) == 1
    assert len(recorder.knowledge_calls) == 1


def test_agent_api_runtime_enabled_calls_tool_and_returns_same_response_shape(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_runtime_enabled", True)
    provider = FakeRuntimeProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    _draft(
                        problem_summary="Runtime diagnosis.",
                        risk_level="low",
                    )
                )
            ),
        ]
    )
    executor = FakeRuntimeExecutor()
    monkeypatch.setattr(runtime_module, "ToolCallExecutor", lambda db: executor)
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    data = response.json()
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
    assert data["problem_summary"] == "Runtime diagnosis."
    assert data["device"]["device_code"] == "DEV-001"
    assert data["sources"] == ["manual.md#chunk-0"]
    assert data["tools_used"] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert data["risk_level"] == "high"
    assert executor.calls == [
        ("get_device_status", {"device_code": "DEV-001"}),
        ("get_device_alarms", {"device_code": "DEV-001", "limit": 20, "unresolved_only": True}),
        (
            "search_knowledge",
            {
                "query": (
                    "E101 high alarm E101 温度过高 "
                    f"{QUERY_DIAGNOSIS} pump maintenance handling steps"
                ),
                "top_k": 5,
            },
        ),
    ]


def test_agent_api_runtime_trace_endpoint_keeps_diagnose_shape_unchanged(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_runtime_enabled", True)
    provider = FakeRuntimeProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    _draft(
                        problem_summary="Runtime diagnosis.",
                        risk_level="low",
                    )
                )
            ),
        ]
    )
    executor = FakeRuntimeExecutor()
    monkeypatch.setattr(runtime_module, "ToolCallExecutor", lambda db: executor)
    app.dependency_overrides[get_llm_provider] = lambda: provider

    diagnose_response = agent_client.post(
        "/agent/diagnose",
        json={"query": QUERY_DIAGNOSIS},
    )
    trace_response = agent_client.get("/agent/debug/trace/latest")

    assert diagnose_response.status_code == 200
    assert "trace" not in diagnose_response.json()
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["mode"] == "runtime"
    assert trace["query"] == QUERY_DIAGNOSIS
    assert trace["router_tools"] == ["get_device_status", "get_device_alarms", "search_knowledge"]
    assert [result["tool_name"] for result in trace["tool_results"]] == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]
    assert trace["rag_results"] == [
        {
            "chunk_id": 1,
            "document_id": 1,
            "filename": "manual-1.md",
            "chunk_index": 0,
            "source": "manual.md#chunk-0",
            "distance": 0.2,
            "content": "E101 high temperature maintenance guidance.",
            "device_code": "DEV-001",
            "alarm_code": "E101",
            "query": (
                "E101 high alarm E101 温度过高 "
                f"{QUERY_DIAGNOSIS} pump maintenance handling steps"
            ),
        }
    ]
    assert trace["llm_final_status"]["status"] == "success"


def test_agent_api_saves_diagnosis_history_with_full_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, _provider = _build_conversation_test_client(monkeypatch)
    monkeypatch.setattr(settings, "agent_runtime_enabled", True)
    provider = FakeRuntimeProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="get_device_status",
                        arguments={"device_code": "DEV-001"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(
                content=json.dumps(
                    _draft(
                        problem_summary="Saved runtime diagnosis.",
                        risk_level="medium",
                    )
                )
            ),
        ]
    )
    executor = FakeRuntimeExecutor()
    monkeypatch.setattr(runtime_module, "ToolCallExecutor", lambda db: executor)
    app.dependency_overrides[get_llm_provider] = lambda: provider

    try:
        diagnose_response = client.post(
            "/agent/diagnose",
            json={"query": QUERY_DIAGNOSIS},
        )
        history_response = client.get("/diagnosis/history")

        assert diagnose_response.status_code == 200
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 1
        assert history[0]["device_code"] == "DEV-001"
        assert history[0]["problem_summary"] == "Saved runtime diagnosis."
        assert history[0]["confidence"] is not None
        assert history[0]["sources"] == ["manual.md#chunk-0"]
        assert history[0]["tools_used"] == [
            "get_device_status",
            "get_device_alarms",
            "search_knowledge",
        ]

        detail_response = client.get(
            f"/diagnosis/history/{history[0]['report_id']}"
        )
        numeric_detail_response = client.get("/diagnosis/history/1")

        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert numeric_detail_response.status_code == 200
        assert numeric_detail_response.json()["report_id"] == history[0]["report_id"]
        assert detail["query"] == QUERY_DIAGNOSIS
        assert detail["response"]["problem_summary"] == "Saved runtime diagnosis."
        assert detail["response"]["device"]["device_code"] == "DEV-001"
        assert detail["tools_used"] == [
            "get_device_status",
            "get_device_alarms",
            "search_knowledge",
        ]
        assert detail["rag_sources"][0]["source"] == "manual.md#chunk-0"
        assert detail["rag_sources"][0]["content"] == (
            "E101 high temperature maintenance guidance."
        )
        assert detail["trace"]["llm_final_status"]["status"] == "success"

        db = SessionLocal()
        try:
            report_v2 = db.query(DiagnosisReport).one()
            trace_rows = db.query(DiagnosisTrace).order_by(DiagnosisTrace.id).all()
            assert report_v2.report_id == history[0]["report_id"]
            assert report_v2.report_version == "2.0"
            assert report_v2.provider_type
            assert report_v2.generation_status == "completed"
            assert report_v2.report_json["report_version"] == "2.0"
            assert report_v2.report_json["conclusion"]
            assert report_v2.report_json["risk"]["level"] == "high"
            assert [row.step for row in trace_rows] == [
                "router",
                "tool",
                "tool",
                "tool",
                "llm",
            ]
            assert trace_rows[0].report_id == history[0]["report_id"]
            assert trace_rows[-1].status == "success"
        finally:
            db.close()
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_diagnosis_history_detail_not_found_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, _provider = _build_conversation_test_client(monkeypatch)

    try:
        response = client.get("/diagnosis/history/missing-report")

        assert response.status_code == 404
        assert response.json() == {"detail": "Diagnosis report not found."}
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_agent_api_runtime_tool_result_is_sent_to_next_llm_round(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_runtime_enabled", True)
    provider = FakeRuntimeProvider(
        [
            AgentRuntimeLLMResponse(
                tool_calls=[
                    AgentRuntimeToolCall(
                        id="call_1",
                        name="search_knowledge",
                        arguments={"query": "E101报警"},
                    )
                ]
            ),
            AgentRuntimeLLMResponse(content=json.dumps(_draft())),
        ]
    )
    executor = FakeRuntimeExecutor()
    monkeypatch.setattr(runtime_module, "ToolCallExecutor", lambda db: executor)
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_KNOWLEDGE})

    assert response.status_code == 200
    second_round_messages = provider.calls[1]["messages"]
    tool_message = next(
        message
        for message in second_round_messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_1"
    )
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "search_knowledge"
    assert json.loads(tool_message["content"])["result"]["results"][0]["source"] == (
        "manual.md#chunk-0"
    )


def test_agent_api_without_conversation_id_keeps_single_turn_behavior(
    agent_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    provider = MockLLMProvider(response=_draft())
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = agent_client.post("/agent/diagnose", json={"query": QUERY_DIAGNOSIS})

    assert response.status_code == 200
    assert len(provider.calls) == 1
    assert [message.role for message in provider.calls[0]] == ["system", "user"]


def test_agent_api_conversation_first_turn_saves_user_and_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, provider = _build_conversation_test_client(monkeypatch)
    db = SessionLocal()
    try:
        conversation = conversation_service.create_conversation(
            db,
            ConversationCreate(conversation_id="conv-api-001", title="Diagnosis"),
        )
    finally:
        db.close()

    response = client.post(
        "/agent/diagnose",
        json={
            "conversation_id": "conv-api-001",
            "query": QUERY_DIAGNOSIS,
            "knowledge_top_k": 5,
            "include_device_status": True,
            "include_knowledge": True,
        },
    )

    assert response.status_code == 200
    assert len(provider.calls) == 1
    assert [message.role for message in provider.calls[0]] == ["system", "user"]

    db = SessionLocal()
    try:
        messages = conversation_service.get_recent_messages(
            db,
            conversation.conversation_id,
            limit=10,
        )
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == QUERY_DIAGNOSIS
        assert "Draft summary." in messages[1].content
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_agent_api_conversation_second_turn_reads_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, provider = _build_conversation_test_client(monkeypatch)
    db = SessionLocal()
    try:
        conversation = conversation_service.create_conversation(
            db,
            ConversationCreate(conversation_id="conv-api-002", title="Diagnosis"),
        )
        conversation_service.add_message(
            db,
            conversation,
            MessageCreate(role="user", content="上一轮用户问题"),
        )
        conversation_service.add_message(
            db,
            conversation,
            MessageCreate(role="assistant", content="上一轮助手回答"),
        )
    finally:
        db.close()

    response = client.post(
        "/agent/diagnose",
        json={
            "conversation_id": "conv-api-002",
            "query": QUERY_DIAGNOSIS,
            "knowledge_top_k": 5,
            "include_device_status": True,
            "include_knowledge": True,
        },
    )

    assert response.status_code == 200
    assert len(provider.calls) == 1
    assert [message.role for message in provider.calls[0]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert provider.calls[0][1].content == "上一轮用户问题"
    assert provider.calls[0][2].content == "上一轮助手回答"
    assert QUERY_DIAGNOSIS in provider.calls[0][3].content

    db = SessionLocal()
    try:
        messages = conversation_service.get_recent_messages(
            db,
            conversation.conversation_id,
            limit=10,
        )
        assert [message.role for message in messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_agent_api_conversation_history_guides_second_turn_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, _provider = _build_conversation_test_client(monkeypatch)
    search_queries: list[str] = []

    def run_knowledge(input_data: KnowledgeSearchToolInput) -> KnowledgeSearchToolResult:
        search_queries.append(input_data.query)
        if "E203" in input_data.query:
            return _knowledge_result(sources=["e203_controller_manual.md#chunk-0"])
        return _knowledge_result(sources=["e404_controller_manual.md#chunk-0"])

    monkeypatch.setattr(workflow, "run_search_knowledge_tool", run_knowledge)

    db = SessionLocal()
    try:
        conversation = conversation_service.create_conversation(
            db,
            ConversationCreate(conversation_id="conv-api-e203", title="E203"),
        )
    finally:
        db.close()

    try:
        first_response = client.post(
            "/agent/diagnose",
            json={
                "conversation_id": conversation.conversation_id,
                "query": "DEV-001\u51fa\u73b0E203\u62a5\u8b66\u662f\u4ec0\u4e48\u539f\u56e0\uff1f",
                "knowledge_top_k": 5,
                "include_device_status": True,
                "include_knowledge": True,
            },
        )
        second_response = client.post(
            "/agent/diagnose",
            json={
                "conversation_id": conversation.conversation_id,
                "query": "\u90a3\u5e94\u8be5\u600e\u4e48\u5904\u7406\uff1f",
                "knowledge_top_k": 5,
                "include_device_status": True,
                "include_knowledge": True,
            },
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert "E203" in search_queries[-1]
        assert "\u90a3\u5e94\u8be5\u600e\u4e48\u5904\u7406" in search_queries[-1]
        assert second_response.json()["sources"] == [
            "e203_controller_manual.md#chunk-0"
        ]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def _build_conversation_test_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, sessionmaker, MockLLMProvider]:
    monkeypatch.setattr(settings, "agent_runtime_enabled", False)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    provider = MockLLMProvider(response=_draft())
    _patch_tools(monkeypatch)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app), SessionLocal, provider


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


class FakeRuntimeProvider:
    def __init__(self, responses: list[AgentRuntimeLLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str | dict = "auto",
    ) -> AgentRuntimeLLMResponse:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        return self.responses.pop(0)


class FakeRuntimeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append((tool_name, arguments))
        if tool_name == "get_device_status":
            return {
                "tool_name": tool_name,
                "success": True,
                "result": _device_result(["high"]).model_dump(mode="json"),
                "error": None,
            }

        if tool_name == "search_knowledge":
            return {
                "tool_name": tool_name,
                "success": True,
                "result": _knowledge_result().model_dump(mode="json"),
                "error": None,
            }

        if tool_name == "get_device_alarms":
            return {
                "tool_name": tool_name,
                "success": True,
                "result": {
                    "ok": True,
                    "error_code": None,
                    "alarms": [
                        {
                            "device_id": "DEV-001",
                            "alarm_code": "E101",
                            "alarm_name": "温度过高",
                            "level": "high",
                            "status": "unresolved",
                            "created_at": "2026-07-16T15:48:42",
                        }
                    ],
                    "warnings": [],
                },
                "error": None,
            }

        return {
            "tool_name": tool_name,
            "success": False,
            "result": {},
            "error": "tool_not_found",
        }
