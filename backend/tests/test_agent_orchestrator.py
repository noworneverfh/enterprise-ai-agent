import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.agent.orchestrator import DiagnosisOrchestrator  # noqa: E402
from app.agent.orchestrator.context import DiagnosisTrace, ToolExecutionRecord  # noqa: E402
from app.agent.orchestrator.orchestrator import _knowledge_sources  # noqa: E402
from app.agent.orchestrator.planner import IntentPlanner  # noqa: E402
from app.llm.base import LLMMessage  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    AgentDiagnoseRequest,
    AgentDiagnosisDraft,
    MultiDeviceRiskDraft,
    MultiDeviceRiskRequest,
)


def test_intent_planner_builds_enterprise_tool_plan_for_device_fault() -> None:
    plan = IntentPlanner().plan_single(
        AgentDiagnoseRequest(
            device_code="DEV-003",
            query="分析设备温度异常原因",
        )
    )

    assert plan.device_code == "DEV-003"
    assert plan.tool_names == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_orchestrator_passes_evidence_bundle_to_llm() -> None:
    provider = FakeProvider()
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = FakeEngine(
        status_result=_device_status_result("DEV-003", alarm_code="E101"),
        alarms_result=_alarms_result("DEV-003", "E101", "温度异常"),
        knowledge_results=[
            _knowledge_result("e101_maintenance_manual.md#chunk-0", "E101 温度异常维护手册")
        ],
    )

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-003",
            query="分析设备温度异常原因",
        )
    )

    assert response.device.device_code == "DEV-003"
    assert response.sources == ["e101_maintenance_manual.md#chunk-0"]
    assert response.tools_used == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
        "llm_reasoning",
    ]
    llm_payload = json.loads(provider.calls[0][1].content)
    assert "evidence_bundle" in llm_payload
    assert llm_payload["evidence_bundle"]["alarm_facts"]
    assert llm_payload["evidence_bundle"]["knowledge_evidence"]


def test_knowledge_sources_fall_back_to_successful_tool_records() -> None:
    from app.agent.orchestrator.context import DiagnosisOrchestratorContext

    context = DiagnosisOrchestratorContext(
        mode="runtime",
        query="diagnose vibration abnormality",
        device_code="DEV-005",
        planned_tools=["get_device_status", "get_device_alarms", "search_knowledge"],
        trace=DiagnosisTrace(mode="runtime", device_id="DEV-005"),
    )
    context.tool_records.append(
        _record(
            "search_knowledge",
            {"query": "E201 vibration abnormality", "top_k": 5},
            _knowledge_result("e201_vibration_manual.md#chunk-0", "E201 vibration manual"),
        )
    )

    assert _knowledge_sources(context) == ["e201_vibration_manual.md#chunk-0"]


def test_orchestrator_blocks_mismatched_user_concern_before_rag() -> None:
    provider = FakeProvider()
    engine = FakeEngine(
        status_result=_device_status_result("DEV-003", alarm_code="E101", vibration=0.12),
        alarms_result=_alarms_result("DEV-003", "E101", "温度异常"),
        knowledge_results=[
            _knowledge_result("e101_maintenance_manual.md#chunk-0", "E101 温度异常维护手册")
        ],
    )
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = engine

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-003",
            query="分析设备振动异常原因",
        )
    )

    assert response.sources == []
    assert "search_knowledge" not in [call[0] for call in engine.calls]
    assert any("does not match" in warning for warning in response.warnings)


def test_orchestrator_infers_fault_code_for_abnormal_user_concern_without_matching_alarm() -> None:
    provider = FakeProvider()
    engine = FakeEngine(
        status_result=_device_status_result("DEV-002", alarm_code="E404", temperature=54.8, current=9.6, vibration=0.36),
        alarms_result=_alarms_result("DEV-002", "E404", "通信异常"),
        knowledge_by_alarm={
            "E101": _knowledge_result("e101_maintenance_manual.md#chunk-0", "E101 温度异常维护手册"),
        },
    )
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = engine

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-002",
            query="分析设备温度异常原因",
        )
    )

    knowledge_calls = [arguments for tool_name, arguments in engine.calls if tool_name == "search_knowledge"]
    assert knowledge_calls
    assert "E101" in knowledge_calls[0]["query"]
    assert "温度异常" in knowledge_calls[0]["query"]
    assert response.sources == ["e101_maintenance_manual.md#chunk-0"]


def test_orchestrator_auto_searches_alarm_knowledge_for_status_query() -> None:
    provider = FakeProvider()
    engine = FakeEngine(
        status_result=_device_status_result("DEV-005", alarm_code="E201", vibration=0.62),
        alarms_result=_alarms_result("DEV-005", "E201", "振动异常"),
        knowledge_by_alarm={
            "E201": _knowledge_result("e201_vibration_manual.md#chunk-0", "E201 振动异常维护手册"),
        },
    )
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = engine

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-005",
            query="分析当前设备状态",
        )
    )

    knowledge_calls = [arguments for tool_name, arguments in engine.calls if tool_name == "search_knowledge"]
    assert knowledge_calls
    assert "E201" in knowledge_calls[0]["query"]
    assert "振动异常" in knowledge_calls[0]["query"]
    assert "search_knowledge" in response.tools_used
    assert response.sources == ["e201_vibration_manual.md#chunk-0"]


def test_orchestrator_fleet_searches_knowledge_per_alarm() -> None:
    provider = FakeProvider()
    engine = FakeEngine(
        devices=["DEV-003", "DEV-005"],
        status_by_device={
            "DEV-003": _device_status_result("DEV-003", alarm_code="E101"),
            "DEV-005": _device_status_result("DEV-005", alarm_code="E201", vibration=0.62),
        },
        alarms_by_device={
            "DEV-003": _alarms_result("DEV-003", "E101", "温度异常"),
            "DEV-005": _alarms_result("DEV-005", "E201", "振动异常"),
        },
        knowledge_by_alarm={
            "E101": _knowledge_result("e101_maintenance_manual.md#chunk-0", "E101 温度异常维护手册"),
            "E201": _knowledge_result("e201_vibration_manual.md#chunk-0", "E201 振动异常维护手册"),
        },
    )
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = engine

    response = orchestrator.run_fleet(MultiDeviceRiskRequest(query="分析当前所有设备风险"))

    assert [call[0] for call in engine.calls].count("search_knowledge") == 2
    assert response.sources == [
        "e101_maintenance_manual.md#chunk-0",
        "e201_vibration_manual.md#chunk-0",
    ]
    assert response.device_risks[0].risk_score >= response.device_risks[1].risk_score
    llm_payload = json.loads(provider.calls[0][1].content)
    assert llm_payload["evidence_bundle"]["knowledge_evidence"]


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    def complete_structured(self, messages: list[LLMMessage], response_model: type[Any]) -> Any:
        self.calls.append(messages)
        if response_model is AgentDiagnosisDraft:
            return AgentDiagnosisDraft(
                problem_summary="基于设备状态、报警记录和知识库依据生成诊断结论。",
                risk_level="medium",
                possible_causes=["需要结合报警记录和现场参数验证异常原因。"],
                recommended_actions=["按报警类型检查设备状态并记录处理结果。"],
                warnings=[],
            )
        if response_model is MultiDeviceRiskDraft:
            return MultiDeviceRiskDraft(
                summary="已完成多设备风险分析。",
                overall_risk_level="high",
                key_findings=["存在未处理报警设备。"],
                recommended_actions=["优先处理高风险设备。"],
                warnings=[],
            )
        raise AssertionError(response_model)


class FakeEngine:
    def __init__(
        self,
        *,
        devices: list[str] | None = None,
        status_result: dict[str, Any] | None = None,
        alarms_result: dict[str, Any] | None = None,
        knowledge_results: list[dict[str, Any]] | None = None,
        status_by_device: dict[str, dict[str, Any]] | None = None,
        alarms_by_device: dict[str, dict[str, Any]] | None = None,
        knowledge_by_alarm: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.devices = devices or ["DEV-003"]
        self.status_result = status_result
        self.alarms_result = alarms_result
        self.knowledge_results = knowledge_results or []
        self.status_by_device = status_by_device or {}
        self.alarms_by_device = alarms_by_device or {}
        self.knowledge_by_alarm = knowledge_by_alarm or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        trace_context: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        self.calls.append((tool_name, dict(arguments)))
        if tool_name == "list_devices":
            result = {
                "device_count": len(self.devices),
                "device_codes": self.devices,
                "devices": [
                    {
                        "id": index,
                        "device_code": code,
                        "name": f"Device {code}",
                        "device_type": "sensor" if code == "DEV-003" else "motor",
                        "location": "Workshop",
                        "is_online": True,
                        "created_at": _dt(),
                    }
                    for index, code in enumerate(self.devices, start=1)
                ],
            }
            return _record(tool_name, arguments, result)
        if tool_name == "get_device_status":
            code = arguments["device_code"]
            return _record(
                tool_name,
                arguments,
                self.status_by_device.get(code) or self.status_result,
            )
        if tool_name == "get_device_alarms":
            code = arguments.get("device_code")
            return _record(
                tool_name,
                arguments,
                self.alarms_by_device.get(code) or self.alarms_result,
            )
        raise AssertionError(tool_name)

    def search_knowledge(
        self,
        query: str,
        top_k: int,
        *,
        trace_context: dict[str, Any] | None = None,
    ) -> ToolExecutionRecord:
        self.calls.append(("search_knowledge", {"query": query, "top_k": top_k}))
        alarm_code = (trace_context or {}).get("alarm_code")
        result = self.knowledge_by_alarm.get(alarm_code)
        if result is None:
            result = self.knowledge_results[0] if self.knowledge_results else _empty_knowledge()
        return _record("search_knowledge", {"query": query, "top_k": top_k}, result)


def _record(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None,
) -> ToolExecutionRecord:
    now = datetime.now(timezone.utc)
    return ToolExecutionRecord(
        tool_name=tool_name,
        status="success",
        arguments=arguments,
        result=result or {},
        error_code=None,
        started_at=now,
        finished_at=now,
        duration_ms=1,
    )


def _dt() -> str:
    return datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc).isoformat()


def _device_status_result(
    device_code: str,
    *,
    alarm_code: str,
    temperature: float | None = None,
    current: float = 4.5,
    vibration: float = 0.12,
) -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "device_exists": True,
        "device": {
            "id": 3 if device_code == "DEV-003" else 5,
            "device_code": device_code,
            "name": f"Device {device_code}",
            "device_type": "sensor" if device_code == "DEV-003" else "motor",
            "location": "Workshop",
            "is_online": True,
            "created_at": _dt(),
        },
        "latest_runtime_data": {
            "id": 10,
            "device_id": 3 if device_code == "DEV-003" else 5,
            "temperature": temperature if temperature is not None else (68.0 if alarm_code == "E101" else 55.0),
            "voltage": 230.0,
            "current": current,
            "vibration": vibration,
            "status": "warning",
            "recorded_at": _dt(),
            "created_at": _dt(),
        },
        "recent_alarms": [
            {
                "id": 20,
                "device_id": 3 if device_code == "DEV-003" else 5,
                "alarm_code": alarm_code,
                "alarm_level": "medium",
                "message": alarm_display_name_for_test(alarm_code),
                "is_resolved": False,
                "occurred_at": _dt(),
                "resolved_at": None,
                "created_at": _dt(),
            }
        ],
        "warnings": [],
    }


def _alarms_result(device_code: str, alarm_code: str, alarm_name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "alarms": [
            {
                "device_id": device_code,
                "alarm_code": alarm_code,
                "alarm_name": alarm_name,
                "level": "medium",
                "status": "unresolved",
                "created_at": _dt(),
            }
        ],
        "warnings": [],
    }


def _knowledge_result(source: str, filename: str) -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "results": [
            {
                "chunk_id": 1,
                "document_id": 1,
                "filename": filename,
                "chunk_index": 0,
                "content": f"{filename} inspection steps.",
                "source": source,
                "distance": 0.12,
            }
        ],
        "warnings": [],
    }


def _empty_knowledge() -> dict[str, Any]:
    return {"ok": True, "error_code": None, "results": [], "warnings": []}


def alarm_display_name_for_test(alarm_code: str) -> str:
    return {
        "E101": "温度异常",
        "E201": "振动异常",
    }.get(alarm_code, "设备异常")


def test_intent_planner_handles_real_chinese_fault_query() -> None:
    plan = IntentPlanner().plan_single(
        AgentDiagnoseRequest(
            device_code="DEV-002",
            query="分析设备温度异常原因",
        )
    )

    assert plan.device_code == "DEV-002"
    assert plan.tool_names == [
        "get_device_status",
        "get_device_alarms",
        "search_knowledge",
    ]


def test_orchestrator_infers_fault_code_for_real_chinese_abnormal_concern() -> None:
    provider = FakeProvider()
    engine = FakeEngine(
        status_result=_device_status_result(
            "DEV-002",
            alarm_code="E404",
            temperature=54.8,
            current=9.6,
            vibration=0.36,
        ),
        alarms_result=_alarms_result("DEV-002", "E404", "通信异常"),
        knowledge_by_alarm={
            "E101": _knowledge_result("e101_maintenance_manual.md#chunk-0", "E101 温度异常维护手册"),
        },
    )
    orchestrator = DiagnosisOrchestrator(db=object(), llm_provider=provider)  # type: ignore[arg-type]
    orchestrator.engine = engine

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-002",
            query="分析设备温度异常原因",
        )
    )

    knowledge_calls = [
        arguments for tool_name, arguments in engine.calls if tool_name == "search_knowledge"
    ]
    assert knowledge_calls
    assert "E101" in knowledge_calls[0]["query"]
    assert "温度异常" in knowledge_calls[0]["query"]
    assert response.sources == ["e101_maintenance_manual.md#chunk-0"]
