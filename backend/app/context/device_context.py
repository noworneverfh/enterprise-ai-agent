from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.diagnosis.alarm_catalog import alarm_display_name
from app.domain.diagnosis.parameter_rules import evaluate_runtime_parameters
from app.domain.diagnosis.risk_engine import calculate_risk_assessment
from app.models.alarm import DeviceAlarmRecord
from app.models.context import DeviceRiskTimeline, MaintenanceRecord
from app.models.device import Device
from app.models.diagnosis import DiagnosisRecord
from app.models.knowledge_structured import FaultKnowledgeEntry, MaintenanceCase
from app.models.runtime import DeviceRuntimeData
from app.services import device as device_service

from .schemas import (
    DeviceContext,
    DeviceContextAlarm,
    DeviceContextDevice,
    DeviceContextDiagnosisHistory,
    DeviceContextKnowledgeLink,
    DeviceContextMaintenanceMemory,
    DeviceContextRiskPoint,
    DeviceContextRuntimePoint,
    DeviceContextSimilarCase,
    DeviceHealthSummary,
)


def build_device_context(
    db: Session,
    device_code: str,
    *,
    runtime_limit: int = 20,
    alarm_limit: int = 50,
    diagnosis_limit: int = 10,
    maintenance_limit: int = 10,
    risk_limit: int = 20,
) -> DeviceContext:
    """Build a long-term device profile from trusted enterprise data."""

    device = device_service.get_device_by_code(db, device_code)
    if device is None:
        return DeviceContext(exists=False)

    runtime_history = [
        DeviceContextRuntimePoint.model_validate(runtime)
        for runtime in device_service.list_runtime_data(db, device, limit=runtime_limit)
    ]
    current_runtime = runtime_history[0] if runtime_history else None
    current_alarms = [
        _alarm_context(alarm)
        for alarm in device_service.list_alarm_records(
            db,
            device,
            limit=alarm_limit,
            is_resolved=False,
        )
    ]
    historical_alarms = [
        _alarm_context(alarm)
        for alarm in device_service.list_alarm_records(
            db,
            device,
            limit=alarm_limit,
            is_resolved=None,
        )
    ]
    diagnosis_history = _diagnosis_history(db, device.device_code, diagnosis_limit)
    risk_trend = _risk_trend(db, device, risk_limit, diagnosis_history)
    maintenance_memory = _maintenance_memory(db, device, maintenance_limit)
    related_knowledge = _related_knowledge(db, device, current_alarms, historical_alarms)
    similar_cases = _similar_cases(db, device, current_alarms, historical_alarms)

    return DeviceContext(
        exists=True,
        device=DeviceContextDevice.model_validate(device),
        current_runtime=current_runtime,
        runtime_history=runtime_history,
        current_alarms=current_alarms,
        historical_alarms=historical_alarms,
        diagnosis_history=diagnosis_history,
        risk_trend=risk_trend,
        maintenance_memory=maintenance_memory,
        related_knowledge=related_knowledge,
        similar_cases=similar_cases,
        health_summary=_health_summary(
            device,
            current_runtime,
            current_alarms,
            historical_alarms,
            diagnosis_history,
            risk_trend,
            maintenance_memory,
        ),
    )


def _alarm_context(alarm: DeviceAlarmRecord) -> DeviceContextAlarm:
    return DeviceContextAlarm(
        id=alarm.id,
        alarm_code=alarm.alarm_code,
        alarm_name=alarm_display_name(alarm.alarm_code, alarm.message),
        alarm_level=alarm.alarm_level,
        message=alarm.message,
        is_resolved=alarm.is_resolved,
        occurred_at=alarm.occurred_at,
        resolved_at=alarm.resolved_at,
    )


def _diagnosis_history(
    db: Session,
    device_code: str,
    limit: int,
) -> list[DeviceContextDiagnosisHistory]:
    records = db.scalars(
        select(DiagnosisRecord)
        .where(DiagnosisRecord.device_code == device_code)
        .order_by(DiagnosisRecord.created_at.desc(), DiagnosisRecord.id.desc())
        .limit(limit)
    ).all()
    return [
        DeviceContextDiagnosisHistory(
            report_id=record.report_id,
            query=record.query,
            risk_level=record.risk_level,
            problem_summary=record.problem_summary,
            created_at=record.created_at,
        )
        for record in records
    ]


def _risk_trend(
    db: Session,
    device: Device,
    limit: int,
    diagnosis_history: list[DeviceContextDiagnosisHistory],
) -> list[DeviceContextRiskPoint]:
    points = db.scalars(
        select(DeviceRiskTimeline)
        .where(DeviceRiskTimeline.device_id == device.id)
        .order_by(DeviceRiskTimeline.recorded_at.desc(), DeviceRiskTimeline.id.desc())
        .limit(limit)
    ).all()
    if points:
        return [
            DeviceContextRiskPoint(
                risk_level=point.risk_level,
                risk_score=point.risk_score,
                alarm_count=point.alarm_count,
                abnormal_parameters=_string_list(point.abnormal_parameters),
                report_id=point.report_id,
                recorded_at=point.recorded_at,
            )
            for point in points
        ]

    # Backfill a lightweight trend from historical reports until active monitoring exists.
    result: list[DeviceContextRiskPoint] = []
    for item in diagnosis_history:
        score = {
            "critical": 95,
            "high": 80,
            "medium": 55,
            "low": 30,
            "normal": 10,
        }.get(item.risk_level, 0)
        result.append(
            DeviceContextRiskPoint(
                risk_level=item.risk_level,
                risk_score=score,
                alarm_count=0,
                abnormal_parameters=[],
                report_id=item.report_id,
                recorded_at=item.created_at,
            )
        )
    return result


def _maintenance_memory(
    db: Session,
    device: Device,
    limit: int,
) -> list[DeviceContextMaintenanceMemory]:
    rows = db.scalars(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.device_id == device.id)
        .order_by(MaintenanceRecord.created_at.desc(), MaintenanceRecord.id.desc())
        .limit(limit)
    ).all()
    alarms_by_id = {
        alarm.id: alarm
        for alarm in db.scalars(
            select(DeviceAlarmRecord).where(DeviceAlarmRecord.device_id == device.id)
        ).all()
    }
    return [
        DeviceContextMaintenanceMemory(
            id=row.id,
            report_id=row.report_id,
            alarm_code=(
                alarms_by_id[row.alarm_record_id].alarm_code
                if row.alarm_record_id in alarms_by_id
                else None
            ),
            actual_action=row.actual_action,
            confirmed_root_cause=row.confirmed_root_cause,
            resolved=row.resolved,
            result=row.result,
            performed_at=row.performed_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _related_knowledge(
    db: Session,
    device: Device,
    current_alarms: list[DeviceContextAlarm],
    historical_alarms: list[DeviceContextAlarm],
) -> list[DeviceContextKnowledgeLink]:
    alarm_codes = _alarm_codes([*current_alarms, *historical_alarms])
    conditions = [FaultKnowledgeEntry.device_type == device.device_type]
    if alarm_codes:
        conditions.append(FaultKnowledgeEntry.fault_code.in_(alarm_codes))
    query = select(FaultKnowledgeEntry).where(or_(*conditions))
    entries = db.scalars(query.limit(20)).unique().all()
    return [
        DeviceContextKnowledgeLink(
            fault_code=entry.fault_code,
            fault_name=entry.fault_name,
            severity=entry.severity,
            device_type=entry.device_type,
            document_id=entry.document_id,
            cause_count=len(entry.causes),
            case_count=len(entry.cases),
        )
        for entry in entries
    ]


def _similar_cases(
    db: Session,
    device: Device,
    current_alarms: list[DeviceContextAlarm],
    historical_alarms: list[DeviceContextAlarm],
) -> list[DeviceContextSimilarCase]:
    alarm_codes = _alarm_codes([*current_alarms, *historical_alarms])
    query = select(MaintenanceCase)
    if alarm_codes:
        query = query.where(MaintenanceCase.fault.in_(alarm_codes))
    else:
        query = query.where(MaintenanceCase.device == device.device_code)
    cases = db.scalars(
        query.order_by(MaintenanceCase.created_at.desc(), MaintenanceCase.id.desc()).limit(10)
    ).all()
    return [DeviceContextSimilarCase.model_validate(case) for case in cases]


def _health_summary(
    device: Device,
    current_runtime: DeviceContextRuntimePoint | None,
    current_alarms: list[DeviceContextAlarm],
    historical_alarms: list[DeviceContextAlarm],
    diagnosis_history: list[DeviceContextDiagnosisHistory],
    risk_trend: list[DeviceContextRiskPoint],
    maintenance_memory: list[DeviceContextMaintenanceMemory],
) -> DeviceHealthSummary:
    runtime_payload = current_runtime.model_dump() if current_runtime is not None else {}
    observations = evaluate_runtime_parameters(device.device_type, runtime_payload)
    abnormal_parameters = [
        observation.parameter
        for observation in observations
        if observation.status in {"warning", "critical"}
    ]
    proposed = _level_from_alarms(current_alarms)
    if not proposed and abnormal_parameters:
        proposed = "high" if any(obs.status == "critical" for obs in observations) else "medium"
    if not proposed:
        proposed = "normal" if device.is_online else "unknown"
    risk = calculate_risk_assessment(
        proposed,
        observations=observations,
        alarm_levels=[alarm.alarm_level for alarm in current_alarms],
        is_online=device.is_online,
    )
    return DeviceHealthSummary(
        current_risk_level=risk.level,
        current_risk_score=risk.score,
        unresolved_alarm_count=len(current_alarms),
        historical_alarm_count=len(historical_alarms),
        diagnosis_count=len(diagnosis_history),
        maintenance_record_count=len(maintenance_memory),
        abnormal_parameters=abnormal_parameters,
        trend=_trend(risk_trend),
    )


def _level_from_alarms(alarms: list[DeviceContextAlarm]) -> str | None:
    order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    levels = [alarm.alarm_level.lower() for alarm in alarms]
    if not levels:
        return None
    return max(levels, key=lambda level: order.get(level, 0))


def _trend(points: list[DeviceContextRiskPoint]) -> str:
    if len(points) < 2:
        return "unknown"
    newest, previous = points[0], points[1]
    if newest.risk_score > previous.risk_score + 5:
        return "worsening"
    if newest.risk_score < previous.risk_score - 5:
        return "improving"
    return "stable"


def _alarm_codes(alarms: list[DeviceContextAlarm]) -> list[str]:
    result: list[str] = []
    for alarm in alarms:
        code = alarm.alarm_code.upper()
        if code not in result:
            result.append(code)
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [str(key) for key, enabled in value.items() if enabled]
    return []
