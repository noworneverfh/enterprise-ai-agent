from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_authenticated, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.domain.diagnosis.models import DiagnosisReportV2, FleetRiskReportV2
from app.models.alarm import DeviceAlarmRecord
from app.models.device import Device
from app.models.diagnosis import DiagnosisRecord, DiagnosisReport
from app.models.document import KnowledgeDocument
from app.schemas.agent import AgentDiagnoseResponse, MultiDeviceRiskResponse
from app.schemas.dashboard import (
    DashboardOverviewResponse,
    DiagnosisHistoryDetail,
    DiagnosisHistoryItem,
    DiagnosisRagSource,
    RecentAlarmResponse,
    SystemHealthResponse,
)


router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def get_dashboard_overview(
    _current_user=Depends(require_permission("devices:view")),
    db: Session = Depends(get_db),
) -> DashboardOverviewResponse:
    today_start = datetime.combine(datetime.utcnow().date(), time.min)

    online_devices = db.scalar(
        select(func.count()).select_from(Device).where(Device.is_online.is_(True))
    ) or 0
    knowledge_documents_count = db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(KnowledgeDocument.status == "indexed")
    ) or 0
    today_diagnosis_count = db.scalar(
        select(func.count())
        .select_from(DiagnosisRecord)
        .where(DiagnosisRecord.created_at >= today_start)
    ) or 0
    avg_response_time = db.scalar(
        select(func.avg(DiagnosisRecord.duration_ms)).where(
            DiagnosisRecord.duration_ms.is_not(None)
        )
    )

    return DashboardOverviewResponse(
        online_devices=online_devices,
        today_diagnosis_count=today_diagnosis_count,
        knowledge_documents_count=knowledge_documents_count,
        agent_status=_overall_agent_status(),
        avg_response_time=round(float(avg_response_time), 2)
        if avg_response_time is not None
        else None,
    )


@router.get("/alarms/recent", response_model=list[RecentAlarmResponse])
def get_recent_alarms(
    limit: int = Query(default=6, ge=1, le=50),
    _current_user=Depends(require_permission("devices:view")),
    db: Session = Depends(get_db),
) -> list[RecentAlarmResponse]:
    rows = db.execute(
        select(DeviceAlarmRecord, Device.device_code)
        .join(Device, Device.id == DeviceAlarmRecord.device_id)
        .where(DeviceAlarmRecord.is_resolved.is_(False))
        .order_by(DeviceAlarmRecord.occurred_at.desc())
        .limit(limit)
    ).all()

    return [
        RecentAlarmResponse(
            device_code=device_code,
            alarm_code=alarm.alarm_code,
            alarm_name=_alarm_display_name(alarm.alarm_code),
            alarm_level=alarm.alarm_level,
            status="unresolved" if not alarm.is_resolved else "resolved",
            created_at=alarm.occurred_at,
        )
        for alarm, device_code in rows
    ]


@router.get("/diagnosis/history", response_model=list[DiagnosisHistoryItem])
def get_diagnosis_history(
    limit: int = Query(default=20, ge=1, le=50),
    _current_user=Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> list[DiagnosisHistoryItem]:
    records = db.scalars(
        select(DiagnosisRecord)
        .order_by(DiagnosisRecord.created_at.desc())
        .limit(limit)
    ).all()

    return [
        DiagnosisHistoryItem(
            report_id=record.report_id,
            device_code=record.device_code,
            alarm_code=record.alarm_code,
            alarm_name=_alarm_display_name(record.alarm_code)
            if record.alarm_code
            else None,
            risk_level=record.risk_level,
            status=record.status,
            created_at=record.created_at,
            confidence=_extract_confidence(record.response_json),
            problem_summary=record.problem_summary,
            sources=_extract_sources(record.response_json),
            tools_used=_extract_tools_used(record.response_json),
        )
        for record in records
    ]


@router.get("/diagnosis/history/{report_id}", response_model=DiagnosisHistoryDetail)
def get_diagnosis_report(
    report_id: str,
    _current_user=Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> DiagnosisHistoryDetail:
    filters = [DiagnosisRecord.report_id == report_id]
    if report_id.isdigit():
        filters.append(DiagnosisRecord.id == int(report_id))
    record = db.scalar(select(DiagnosisRecord).where(or_(*filters)))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnosis report not found.",
        )

    response_payload = _extract_response_payload(record.response_json)
    response = (
        AgentDiagnoseResponse.model_validate(response_payload)
        if response_payload is not None
        else None
    )
    risk_report_payload = _extract_risk_report_payload(record.response_json)
    risk_report = (
        MultiDeviceRiskResponse.model_validate(risk_report_payload)
        if risk_report_payload is not None
        else None
    )
    report_v2 = _extract_report_v2(db, record, response_payload, risk_report_payload)

    return DiagnosisHistoryDetail(
        report_id=record.report_id,
        device_code=record.device_code,
        alarm_code=record.alarm_code,
        alarm_name=_alarm_display_name(record.alarm_code) if record.alarm_code else None,
        risk_level=record.risk_level,
        status=record.status,
        query=record.query,
        problem_summary=record.problem_summary,
        response=response,
        risk_report=risk_report,
        tools_used=_extract_tools_used(record.response_json),
        rag_sources=[
            DiagnosisRagSource.model_validate(source)
            for source in _extract_rag_sources(record.response_json)
        ],
        confidence=_extract_confidence(record.response_json),
        duration_ms=record.duration_ms,
        trace=_extract_trace(record.response_json),
        report_v2=report_v2,
        created_at=record.created_at,
    )


@router.get("/system/health", response_model=SystemHealthResponse)
def get_system_health() -> SystemHealthResponse:
    return _component_health()


def _component_health() -> SystemHealthResponse:
    llm_health = "healthy"
    if settings.llm_provider == "openai_compatible":
        if (
            not settings.llm_api_key
            or not settings.llm_base_url
            or not settings.llm_model
        ):
            llm_health = "degraded"

    return SystemHealthResponse(
        router="healthy",
        tools="healthy",
        rag="healthy",
        llm=llm_health,
    )


def _overall_agent_status() -> str:
    health = _component_health()
    statuses = [health.router, health.tools, health.rag, health.llm]
    return "healthy" if all(item == "healthy" for item in statuses) else "degraded"


def _extract_response_payload(response_json: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(response_json.get("response"), dict):
        return response_json["response"]

    if isinstance(response_json.get("risk_report"), dict):
        return None

    return response_json


def _extract_risk_report_payload(response_json: dict[str, Any]) -> dict[str, Any] | None:
    risk_report = response_json.get("risk_report")
    return risk_report if isinstance(risk_report, dict) else None


def _extract_trace(response_json: dict[str, Any]) -> dict[str, Any] | None:
    trace = response_json.get("trace")
    return trace if isinstance(trace, dict) else None


def _extract_report_v2(
    db: Session,
    record: DiagnosisRecord,
    response_payload: dict[str, Any] | None,
    risk_report_payload: dict[str, Any] | None,
) -> DiagnosisReportV2 | FleetRiskReportV2 | None:
    persisted = db.scalar(
        select(DiagnosisReport)
        .where(DiagnosisReport.report_id == record.report_id)
        .order_by(DiagnosisReport.created_at.desc())
    )
    payload: dict[str, Any] | None = None
    if persisted is not None and isinstance(persisted.report_json, dict):
        payload = persisted.report_json
    elif response_payload and isinstance(response_payload.get("report_v2"), dict):
        payload = response_payload["report_v2"]
    elif risk_report_payload and isinstance(risk_report_payload.get("report_v2"), dict):
        payload = risk_report_payload["report_v2"]

    if not payload:
        return None
    if isinstance(payload.get("devices"), list):
        return FleetRiskReportV2.model_validate(payload)
    return DiagnosisReportV2.model_validate(payload)


def _extract_tools_used(response_json: dict[str, Any]) -> list[str]:
    tools = response_json.get("tools_used")
    if isinstance(tools, list):
        return [item for item in tools if isinstance(item, str)]

    payload = _extract_response_payload(response_json)
    if payload is None:
        payload = _extract_risk_report_payload(response_json)
    if payload is None:
        return []

    tools = payload.get("tools_used")
    return [item for item in tools if isinstance(item, str)] if isinstance(tools, list) else []


def _extract_sources(response_json: dict[str, Any]) -> list[str]:
    payload = _extract_response_payload(response_json)
    if payload is None:
        payload = _extract_risk_report_payload(response_json)
    if payload is None:
        return []

    sources = payload.get("sources")
    return [item for item in sources if isinstance(item, str)] if isinstance(sources, list) else []


def _extract_rag_sources(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    rag_sources = response_json.get("rag_sources")
    if isinstance(rag_sources, list) and rag_sources:
        return [
            item
            for item in rag_sources
            if isinstance(item, dict) and isinstance(item.get("source"), str)
        ]

    trace = _extract_trace(response_json)
    trace_sources = trace.get("rag_results", []) if trace else []
    if isinstance(trace_sources, list) and trace_sources:
        return [
            item
            for item in trace_sources
            if isinstance(item, dict) and isinstance(item.get("source"), str)
        ]

    return [{"source": source} for source in _extract_sources(response_json)]


def _extract_confidence(response_json: dict[str, Any]) -> int | None:
    confidence = response_json.get("confidence")
    if isinstance(confidence, int):
        return confidence
    if isinstance(confidence, float):
        return round(confidence)
    return None


def _alarm_display_name(alarm_code: str) -> str:
    names = {
        "E101": "温度异常",
        "E201": "振动异常",
        "E203": "电机运行异常",
        "E404": "通信异常",
    }
    return names.get(alarm_code.upper(), "设备异常")
