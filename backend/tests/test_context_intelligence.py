from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.orchestrator import orchestrator as orchestrator_module
from app.agent.orchestrator import DiagnosisOrchestrator
from app.context.device_context import build_device_context
from app.context.maintenance_memory import create_maintenance_record
from app.context.risk_monitoring import scan_device_risks
from app.context.schemas import (
    DeviceContext,
    DeviceContextAlarm,
    DeviceContextDevice,
    DeviceContextRuntimePoint,
    DeviceHealthSummary,
    MaintenanceRecordCreate,
)
from app.db.base import Base
from app.domain.diagnosis.models import DiagnosisReportV2
from app.llm.base import LLMMessage
from app.models.alarm import DeviceAlarmRecord
from app.models.context import DeviceRiskTimeline, DiagnosisSession, RiskEvent
from app.models.device import Device
from app.models.diagnosis import DiagnosisRecord
from app.models.document import KnowledgeDocument
from app.models.knowledge_structured import (
    FaultCause,
    FaultKnowledgeEntry,
    MaintenanceCase,
)
from app.models.runtime import DeviceRuntimeData
from app.schemas.agent import AgentDiagnoseRequest, AgentDiagnosisDraft


def test_device_context_aggregates_history_knowledge_and_maintenance_memory() -> None:
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        device, alarm = _seed_context_device(db)
        create_maintenance_record(
            db,
            MaintenanceRecordCreate(
                device_code=device.device_code,
                alarm_record_id=alarm.id,
                report_id="report-001",
                actual_action="清理散热通道并校准温度传感器。",
                confirmed_root_cause="散热通道堵塞",
                resolved=True,
                result="温度恢复正常。",
            ),
        )
        db.commit()

        context = build_device_context(db, "DEV-003")

        assert context.exists is True
        assert context.device.device_code == "DEV-003"
        assert context.current_runtime.temperature == 72.0
        assert context.current_alarms[0].alarm_code == "E101"
        assert context.diagnosis_history[0].report_id == "report-001"
        assert context.maintenance_memory[0].confirmed_root_cause == "散热通道堵塞"
        assert context.related_knowledge[0].fault_code == "E101"
        assert context.similar_cases
        assert context.health_summary.current_risk_level in {"high", "critical"}
    finally:
        db.close()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_orchestrator_enriches_llm_and_rag_with_device_context(monkeypatch) -> None:
    provider = RecordingProvider()
    orchestrator = DiagnosisOrchestrator(db=FakeDb(), llm_provider=provider)  # type: ignore[arg-type]
    engine = RecordingEngine()
    orchestrator.engine = engine
    monkeypatch.setattr(
        orchestrator_module,
        "build_device_context",
        lambda db, device_code: _fake_device_context(device_code),
    )

    response = orchestrator.run_single(
        AgentDiagnoseRequest(
            device_code="DEV-003",
            query="分析设备温度异常原因",
        )
    )

    knowledge_queries = [call[1]["query"] for call in engine.calls if call[0] == "search_knowledge"]
    assert knowledge_queries
    assert "散热通道堵塞" in knowledge_queries[0]
    assert "历史温度异常" in knowledge_queries[0]
    llm_payload = provider.last_payload()
    assert llm_payload["device_context"]["health_summary"]["diagnosis_count"] == 2
    assert llm_payload["evidence_bundle"]["history_cases"]
    assert response.tools_used[-1] == "llm_reasoning"


def test_risk_monitoring_creates_risk_event_and_timeline() -> None:
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        _seed_context_device(db)

        events = scan_device_risks(db)
        db.commit()

        assert len(events) == 1
        assert events[0].device_code == "DEV-003"
        assert events[0].risk_level in {"high", "critical"}
        assert db.scalar(select(RiskEvent)) is not None
        assert db.scalar(select(DeviceRiskTimeline)) is not None
    finally:
        db.close()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def test_diagnosis_session_can_store_business_context() -> None:
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        from app.context.schemas import DiagnosisSessionCreate
        from app.context.session_context import persist_diagnosis_session

        persist_diagnosis_session(
            db,
            DiagnosisSessionCreate(
                query="分析设备温度异常原因",
                report_id="report-ctx",
                planned_tools=["get_device_status", "search_knowledge"],
                evidence_summary={"device_context": {"device": "DEV-003"}},
                rag_summary=[{"source": "e101_maintenance_manual.md#chunk-0"}],
                risk_summary={"level": "high", "score": 82},
                report_summary={"conclusion": "存在温度异常风险。"},
            ),
        )
        db.commit()

        session = db.scalar(select(DiagnosisSession))
        assert session is not None
        assert session.report_id == "report-ctx"
        assert session.evidence_summary["device_context"]["device"] == "DEV-003"
    finally:
        db.close()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    def complete_structured(self, messages: list[LLMMessage], response_model: type[Any]) -> Any:
        self.calls.append(messages)
        return AgentDiagnosisDraft(
            problem_summary="设备存在温度异常，需结合历史维修记录确认散热状态。",
            risk_level="high",
            possible_causes=["历史散热通道堵塞可能再次导致温度异常。"],
            recommended_actions=["检查散热通道并复核温度传感器。"],
            warnings=[],
        )

    def last_payload(self) -> dict[str, Any]:
        import json

        return json.loads(self.calls[-1][-1].content)


class FakeDb:
    def scalar(self, *args, **kwargs):
        return None

    def scalars(self, *args, **kwargs):
        return []


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, tool_name: str, arguments: dict[str, Any], *, trace_context=None):
        from app.agent.orchestrator.context import ToolExecutionRecord, now_utc

        self.calls.append((tool_name, dict(arguments)))
        if tool_name == "get_device_status":
            result = _status_result()
        elif tool_name == "get_device_alarms":
            result = _alarms_result()
        else:
            raise AssertionError(tool_name)
        return ToolExecutionRecord(
            tool_name=tool_name,
            status="success",
            arguments=arguments,
            result=result,
            error_code=None,
            started_at=now_utc(),
            finished_at=now_utc(),
            duration_ms=1,
        )

    def search_knowledge(self, query: str, top_k: int, *, trace_context=None):
        from app.agent.orchestrator.context import ToolExecutionRecord, now_utc

        self.calls.append(("search_knowledge", {"query": query, "top_k": top_k}))
        return ToolExecutionRecord(
            tool_name="search_knowledge",
            status="success",
            arguments={"query": query, "top_k": top_k},
            result={
                "ok": True,
                "error_code": None,
                "results": [
                    {
                        "chunk_id": 1,
                        "document_id": 1,
                        "filename": "e101_maintenance_manual.md",
                        "chunk_index": 0,
                        "content": "E101 温度异常与散热通道堵塞有关。",
                        "source": "e101_maintenance_manual.md#chunk-0",
                        "distance": 0.18,
                    }
                ],
                "warnings": [],
            },
            error_code=None,
            started_at=now_utc(),
            finished_at=now_utc(),
            duration_ms=1,
        )


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_context_device(db):
    device = Device(
        device_code="DEV-003",
        name="Temperature Sensor C",
        device_type="sensor",
        location="Workshop C",
        is_online=True,
    )
    db.add(device)
    db.flush()
    db.add(
        DeviceRuntimeData(
            device_id=device.id,
            temperature=72.0,
            voltage=24.0,
            current=1.1,
            vibration=0.12,
            status="warning",
            recorded_at=datetime(2026, 7, 20, 8, 0, 0),
        )
    )
    alarm = DeviceAlarmRecord(
        device_id=device.id,
        alarm_code="E101",
        alarm_level="high",
        message="温度异常",
        is_resolved=False,
        occurred_at=datetime(2026, 7, 20, 8, 1, 0),
    )
    db.add(alarm)
    document = KnowledgeDocument(
        original_filename="e101_maintenance_manual.md",
        storage_filename="e101_maintenance_manual.md",
        file_type="md",
        title="E101 温度异常维护手册",
        device_type="sensor",
        status="indexed",
        chunk_count=1,
    )
    db.add(document)
    db.flush()
    entry = FaultKnowledgeEntry(
        document_id=document.id,
        fault_code="E101",
        fault_name="温度异常",
        description="温度超过安全范围。",
        severity="high",
        device_type="sensor",
        trigger_conditions={"temperature": ">60"},
    )
    db.add(entry)
    db.flush()
    db.add(
        FaultCause(
            fault_entry_id=entry.id,
            cause="散热通道堵塞",
            priority=1,
            evidence="温度持续升高。",
            verification_method="检查滤网和风道。",
        )
    )
    db.add(
        MaintenanceCase(
            fault_entry_id=entry.id,
            device="DEV-003",
            fault="E101",
            symptom="历史温度异常",
            root_cause="散热通道堵塞",
            solution="清理散热通道",
            result="温度恢复正常",
        )
    )
    db.add(
        DiagnosisRecord(
            report_id="report-001",
            device_code="DEV-003",
            alarm_code="E101",
            risk_level="high",
            status="completed",
            query="历史温度异常",
            problem_summary="历史温度异常已处理。",
            response_json={},
            created_at=datetime(2026, 7, 19, 8, 0, 0),
        )
    )
    db.commit()
    return device, alarm


def _fake_device_context(device_code: str) -> DeviceContext:
    return DeviceContext(
        exists=True,
        device=DeviceContextDevice(
            id=3,
            device_code=device_code,
            name="Temperature Sensor C",
            device_type="sensor",
            location="Workshop C",
            is_online=True,
            created_at=datetime(2026, 7, 1, 0, 0, 0),
        ),
        current_runtime=DeviceContextRuntimePoint(
            id=1,
            temperature=72.0,
            voltage=24.0,
            current=1.1,
            vibration=0.12,
            status="warning",
            recorded_at=datetime(2026, 7, 20, 8, 0, 0),
        ),
        current_alarms=[
            DeviceContextAlarm(
                id=1,
                alarm_code="E101",
                alarm_name="温度异常",
                alarm_level="high",
                message="温度异常",
                is_resolved=False,
                occurred_at=datetime(2026, 7, 20, 8, 1, 0),
            )
        ],
        health_summary=DeviceHealthSummary(
            current_risk_level="high",
            current_risk_score=82,
            unresolved_alarm_count=1,
            historical_alarm_count=3,
            diagnosis_count=2,
            maintenance_record_count=1,
            abnormal_parameters=["temperature"],
            trend="worsening",
        ),
        maintenance_memory=[
            {
                "id": 1,
                "report_id": "report-001",
                "alarm_code": "E101",
                "actual_action": "清理散热通道",
                "confirmed_root_cause": "散热通道堵塞",
                "resolved": True,
                "result": "温度恢复正常",
                "performed_at": None,
                "created_at": datetime(2026, 7, 19, 8, 0, 0),
            }
        ],
        similar_cases=[
            {
                "id": 1,
                "device": "DEV-003",
                "fault": "E101",
                "symptom": "历史温度异常",
                "root_cause": "散热通道堵塞",
                "solution": "清理散热通道",
                "result": "温度恢复正常",
                "created_at": datetime(2026, 7, 19, 8, 0, 0),
            }
        ],
    )


def _status_result() -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "device_exists": True,
        "device": {
            "id": 3,
            "device_code": "DEV-003",
            "name": "Temperature Sensor C",
            "device_type": "sensor",
            "location": "Workshop C",
            "is_online": True,
            "created_at": datetime(2026, 7, 1, 0, 0, 0),
        },
        "latest_runtime_data": {
            "id": 1,
            "device_id": 3,
            "temperature": 72.0,
            "voltage": 24.0,
            "current": 1.1,
            "vibration": 0.12,
            "status": "warning",
            "recorded_at": datetime(2026, 7, 20, 8, 0, 0),
            "created_at": datetime(2026, 7, 20, 8, 0, 0),
        },
        "recent_alarms": [],
        "warnings": [],
    }


def _alarms_result() -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "alarms": [
            {
                "device_id": "DEV-003",
                "alarm_code": "E101",
                "alarm_name": "温度异常",
                "level": "high",
                "status": "unresolved",
                "created_at": datetime(2026, 7, 20, 8, 1, 0),
            }
        ],
        "warnings": [],
    }
