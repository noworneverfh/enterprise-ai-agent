from datetime import datetime
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import workflow  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    AgentDiagnoseRequest,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ToolAlarmRecord,
    ToolDeviceInfo,
    ToolKnowledgeResult,
)


QUERY_STATUS = "\u67e5\u8be2 DEV-001 \u5f53\u524d\u72b6\u6001\u3002"
QUERY_FAULT_CODE = "E101 \u62a5\u8b66\u4e00\u822c\u662f\u4ec0\u4e48\u539f\u56e0\uff1f"
QUERY_DIAGNOSIS = (
    "DEV-001 \u51fa\u73b0 E101 \u62a5\u8b66\u5e76\u6301\u7eed"
    "\u5347\u6e29\uff0c\u5e94\u8be5\u600e\u4e48\u5904\u7406\uff1f"
)
QUERY_OVERHEAT = "\u8bbe\u5907\u6e29\u5ea6\u8fc7\u9ad8\u600e\u4e48\u529e\uff1f"
QUERY_DEVICE_INFO = "\u4ecb\u7ecd\u4e00\u4e0b DEV-001\u3002"
QUERY_HELLO = "\u4f60\u597d\u3002"


class ToolRecorder:
    def __init__(
        self,
        device_result: DeviceStatusToolResult | None = None,
        knowledge_result: KnowledgeSearchToolResult | None = None,
    ) -> None:
        self.device_result = device_result or _device_result()
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


def test_status_query_calls_only_device_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(object(), AgentDiagnoseRequest(query=QUERY_STATUS))

    assert context.parsed_query.intent == "device_status_query"
    assert context.tools_attempted == ["get_device_status"]
    assert context.tools_succeeded == ["get_device_status"]
    assert len(recorder.device_calls) == 1
    assert recorder.device_calls[0].device_code == "DEV-001"
    assert recorder.knowledge_calls == []


def test_fault_code_query_calls_only_knowledge_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_FAULT_CODE),
    )

    assert context.parsed_query.intent == "knowledge_query"
    assert context.tools_attempted == ["search_knowledge"]
    assert recorder.device_calls == []
    assert len(recorder.knowledge_calls) == 1


def test_diagnosis_query_calls_device_then_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch, device_result=_device_result(["high"]))

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DIAGNOSIS),
    )

    assert context.parsed_query.intent == "diagnosis"
    assert context.tools_attempted == ["get_device_status", "search_knowledge"]
    assert len(recorder.device_calls) == 1
    assert len(recorder.knowledge_calls) == 1
    assert "E101" in recorder.knowledge_calls[0].query


def test_fault_symptom_without_device_calls_only_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_OVERHEAT),
    )

    assert context.parsed_query.intent == "knowledge_query"
    assert context.tools_attempted == ["search_knowledge"]
    assert recorder.device_calls == []
    assert len(recorder.knowledge_calls) == 1


def test_device_info_query_calls_only_device_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DEVICE_INFO),
    )

    assert context.parsed_query.intent == "device_info_query"
    assert context.tools_attempted == ["get_device_status"]
    assert len(recorder.device_calls) == 1
    assert recorder.knowledge_calls == []


def test_small_talk_calls_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_HELLO),
    )

    assert context.parsed_query.intent == "small_talk_or_unknown"
    assert context.tools_attempted == []
    assert recorder.device_calls == []
    assert recorder.knowledge_calls == []


def test_explicit_device_code_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_STATUS, device_code=" dev-002 "),
    )

    assert context.parsed_query.device_code == "DEV-002"
    assert recorder.device_calls[0].device_code == "DEV-002"


def test_include_device_status_false_blocks_device_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(
            query=QUERY_DIAGNOSIS,
            include_device_status=False,
        ),
    )

    assert context.tools_attempted == ["search_knowledge"]
    assert recorder.device_calls == []
    assert len(recorder.knowledge_calls) == 1


def test_include_knowledge_false_blocks_knowledge_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(
            query=QUERY_DIAGNOSIS,
            include_knowledge=False,
        ),
    )

    assert context.tools_attempted == ["get_device_status"]
    assert len(recorder.device_calls) == 1
    assert recorder.knowledge_calls == []


def test_device_not_found_still_continues_to_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch, device_result=_device_not_found_result())

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DIAGNOSIS),
    )

    assert context.device_tool_result.device_exists is False
    assert context.tools_attempted == ["get_device_status", "search_knowledge"]
    assert context.tools_succeeded == ["get_device_status", "search_knowledge"]
    assert len(recorder.knowledge_calls) == 1


def test_device_tool_failure_still_continues_to_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch, device_result=_device_failure_result())

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DIAGNOSIS),
    )

    assert context.tools_attempted == ["get_device_status", "search_knowledge"]
    assert context.tools_succeeded == ["search_knowledge"]
    assert "Device status tool unavailable." in context.warnings
    assert len(recorder.knowledge_calls) == 1


def test_knowledge_tool_failure_retains_device_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(monkeypatch, knowledge_result=_knowledge_failure_result())

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DIAGNOSIS),
    )

    assert context.device_tool_result is not None
    assert context.device_tool_result.ok is True
    assert context.knowledge_tool_result.ok is False
    assert context.tools_succeeded == ["get_device_status"]
    assert context.allowed_sources == []
    assert "Knowledge search tool unavailable." in context.warnings
    assert len(recorder.device_calls) == 1


def test_allowed_sources_only_come_from_knowledge_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_tools(
        monkeypatch,
        knowledge_result=_knowledge_result(
            sources=["manual-a.md#chunk-0", "manual-b.md#chunk-2"]
        ),
    )

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=f"{QUERY_FAULT_CODE} fake-source.md#chunk-99"),
    )

    assert context.allowed_sources == ["manual-a.md#chunk-0", "manual-b.md#chunk-2"]
    assert len(recorder.knowledge_calls) == 1


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        (["critical"], "critical"),
        (["high", "medium"], "high"),
        (["medium", "low"], "medium"),
        (["low"], "low"),
        ([], "unknown"),
    ],
)
def test_calculate_minimum_risk_level(levels: list[str], expected: str) -> None:
    assert workflow.calculate_minimum_risk_level(_device_result(levels)) == expected


def test_each_tool_is_called_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _patch_tools(monkeypatch)

    context = workflow.build_agent_context(
        object(),
        AgentDiagnoseRequest(query=QUERY_DIAGNOSIS),
    )

    assert context.tools_attempted == ["get_device_status", "search_knowledge"]
    assert len(recorder.device_calls) == 1
    assert len(recorder.knowledge_calls) == 1


def test_request_rejects_invalid_fields() -> None:
    with pytest.raises(ValidationError):
        AgentDiagnoseRequest(query="   ")

    with pytest.raises(ValidationError):
        AgentDiagnoseRequest(query=QUERY_STATUS, device_code="abc")

    with pytest.raises(ValidationError):
        AgentDiagnoseRequest(query=QUERY_STATUS, knowledge_top_k=0)

    with pytest.raises(ValidationError):
        AgentDiagnoseRequest(query=QUERY_STATUS, knowledge_top_k=6)


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


def _device_result(levels: list[str] | None = None) -> DeviceStatusToolResult:
    now = datetime.utcnow()
    return DeviceStatusToolResult(
        ok=True,
        device_exists=True,
        device=ToolDeviceInfo(
            id=1,
            device_code="DEV-001",
            name="Demo Device",
            device_type="pump",
            location="Workshop A",
            is_online=True,
            created_at=now,
        ),
        latest_runtime_data=None,
        recent_alarms=[
            ToolAlarmRecord(
                id=index + 1,
                device_id=1,
                alarm_code=f"E10{index + 1}",
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


def _device_failure_result() -> DeviceStatusToolResult:
    return DeviceStatusToolResult(
        ok=False,
        error_code="device_query_failed",
        device_exists=None,
        warnings=["Device status query failed."],
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


def _knowledge_failure_result() -> KnowledgeSearchToolResult:
    return KnowledgeSearchToolResult(
        ok=False,
        error_code="knowledge_search_failed",
        results=[],
        warnings=["Knowledge search failed."],
    )
