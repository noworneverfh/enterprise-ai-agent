from datetime import datetime
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import tool_executor as executor_module  # noqa: E402
from app.agent.tool_executor import ToolCallExecutor  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    DeviceAlarmsToolInput,
    DeviceAlarmsToolResult,
    DeviceStatusToolInput,
    DeviceStatusToolResult,
    KnowledgeSearchToolInput,
    KnowledgeSearchToolResult,
    ToolDeviceAlarm,
    ToolDeviceInfo,
    ToolKnowledgeResult,
)


def test_executor_runs_get_device_status(monkeypatch) -> None:
    calls: list[tuple[object, DeviceStatusToolInput]] = []
    db = object()

    def run_device(
        db_arg: object,
        input_data: DeviceStatusToolInput,
    ) -> DeviceStatusToolResult:
        calls.append((db_arg, input_data))
        return _device_result()

    monkeypatch.setattr(
        executor_module.agent_tools,
        "run_get_device_status_tool",
        run_device,
    )

    result = ToolCallExecutor(db).execute(
        "get_device_status",
        {"device_code": " dev-001 ", "alarm_limit": 3},
    )

    assert result["tool_name"] == "get_device_status"
    assert result["success"] is True
    assert result["error"] is None
    assert result["result"]["ok"] is True
    assert result["result"]["device"]["device_code"] == "DEV-001"
    assert calls[0][0] is db
    assert calls[0][1].device_code == "DEV-001"
    assert calls[0][1].alarm_limit == 3


def test_executor_runs_search_knowledge(monkeypatch, caplog) -> None:
    caplog.set_level("INFO")
    calls: list[KnowledgeSearchToolInput] = []

    def run_knowledge(input_data: KnowledgeSearchToolInput) -> KnowledgeSearchToolResult:
        calls.append(input_data)
        return _knowledge_result()

    monkeypatch.setattr(
        executor_module.agent_tools,
        "run_search_knowledge_tool",
        run_knowledge,
    )

    result = ToolCallExecutor(object()).execute(
        "search_knowledge",
        '{"query": " E203报警 ", "top_k": 2}',
    )

    assert result["tool_name"] == "search_knowledge"
    assert result["success"] is True
    assert result["error"] is None
    assert result["result"]["ok"] is True
    assert result["result"]["results"][0]["source"] == "e203_manual.md#chunk-0"
    assert calls[0].query == "E203报警"
    assert calls[0].top_k == 2
    assert "Agent tool call arguments received" in caplog.text
    assert "tool_name=search_knowledge" in caplog.text
    assert '"top_k": 2' in caplog.text


def test_executor_runs_get_device_alarms(monkeypatch) -> None:
    calls: list[tuple[object, DeviceAlarmsToolInput]] = []
    db = object()

    def run_alarms(
        db_arg: object,
        input_data: DeviceAlarmsToolInput,
    ) -> DeviceAlarmsToolResult:
        calls.append((db_arg, input_data))
        return _alarms_result()

    monkeypatch.setattr(
        executor_module.agent_tools,
        "run_get_device_alarms_tool",
        run_alarms,
    )

    result = ToolCallExecutor(db).execute(
        "get_device_alarms",
        {"device_code": " dev-001 ", "limit": 3},
    )

    assert result["tool_name"] == "get_device_alarms"
    assert result["success"] is True
    assert result["result"]["ok"] is True
    assert result["result"]["alarms"][0]["device_id"] == "DEV-001"
    assert calls[0][0] is db
    assert calls[0][1].device_code == "DEV-001"
    assert calls[0][1].limit == 3


def test_executor_returns_error_for_unknown_tool() -> None:
    result = ToolCallExecutor(object()).execute(
        "missing_tool",
        {"query": "E203"},
    )

    assert result == {
        "tool_name": "missing_tool",
        "success": False,
        "result": {},
        "error": "tool_not_found",
    }


def test_executor_returns_error_for_invalid_arguments(caplog) -> None:
    caplog.set_level("INFO")

    result = ToolCallExecutor(object()).execute(
        "search_knowledge",
        {"query": "E203", "top_k": 99},
    )

    assert result == {
        "tool_name": "search_knowledge",
        "success": False,
        "result": {},
        "error": "invalid_arguments",
    }
    assert "Knowledge search tool arguments invalid" in caplog.text
    assert "query=E203" in caplog.text
    assert "top_k=99" in caplog.text
    assert "exception_type=ValidationError" in caplog.text


def test_executor_returns_error_for_tool_execution_failure(monkeypatch) -> None:
    def fail(input_data: KnowledgeSearchToolInput) -> KnowledgeSearchToolResult:
        raise RuntimeError("internal provider failure")

    monkeypatch.setattr(
        executor_module.agent_tools,
        "run_search_knowledge_tool",
        fail,
    )

    result = ToolCallExecutor(object()).execute(
        "search_knowledge",
        {"query": "E203"},
    )

    assert result == {
        "tool_name": "search_knowledge",
        "success": False,
        "result": {},
        "error": "tool_execution_failed",
    }


def _device_result() -> DeviceStatusToolResult:
    now = datetime.utcnow()
    return DeviceStatusToolResult(
        ok=True,
        error_code=None,
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
        recent_alarms=[],
        warnings=["No runtime data found for device."],
    )


def _knowledge_result() -> KnowledgeSearchToolResult:
    return KnowledgeSearchToolResult(
        ok=True,
        results=[
            ToolKnowledgeResult(
                chunk_id=1,
                document_id=1,
                filename="e203_manual.md",
                chunk_index=0,
                content="E203 controller alarm handling.",
                source="e203_manual.md#chunk-0",
                distance=0.2,
            )
        ],
        warnings=[],
    )


def _alarms_result() -> DeviceAlarmsToolResult:
    return DeviceAlarmsToolResult(
        ok=True,
        alarms=[
            ToolDeviceAlarm(
                device_id="DEV-001",
                alarm_code="E203",
                alarm_name="电机运行异常",
                level="medium",
                status="unresolved",
                created_at=datetime.utcnow(),
            )
        ],
        warnings=[],
    )
