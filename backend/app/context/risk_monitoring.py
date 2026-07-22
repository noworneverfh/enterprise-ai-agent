from __future__ import annotations

from sqlalchemy.orm import Session

from app.context.device_context import build_device_context
from app.context.schemas import RiskEventSummary
from app.models.context import DeviceContextSnapshot, DeviceRiskTimeline, RiskEvent
from app.services import device as device_service


def scan_device_risks(db: Session) -> list[RiskEventSummary]:
    """Active monitoring pass that discovers risk events from current and historical context."""

    summaries: list[RiskEventSummary] = []
    for device in device_service.list_devices(db):
        context = build_device_context(db, device.device_code)
        health = context.health_summary
        if health is None:
            continue

        db.add(
            DeviceContextSnapshot(
                device_id=device.id,
                snapshot_json=context.compact(),
                risk_level=health.current_risk_level,
                risk_score=health.current_risk_score,
            )
        )
        db.add(
            DeviceRiskTimeline(
                device_id=device.id,
                risk_level=health.current_risk_level,
                risk_score=health.current_risk_score,
                alarm_count=health.unresolved_alarm_count,
                abnormal_parameters=health.abnormal_parameters,
            )
        )

        if health.current_risk_level in {"medium", "high", "critical"}:
            event = RiskEvent(
                device_id=device.id,
                event_type=_event_type(health.abnormal_parameters, health.unresolved_alarm_count),
                risk_level=health.current_risk_level,
                risk_score=health.current_risk_score,
                summary=_summary(device.device_code, health),
                evidence={
                    "device_code": device.device_code,
                    "unresolved_alarm_count": health.unresolved_alarm_count,
                    "abnormal_parameters": health.abnormal_parameters,
                    "trend": health.trend,
                    "related_knowledge": [
                        item.model_dump(mode="json") for item in context.related_knowledge[:5]
                    ],
                    "similar_cases": [
                        item.model_dump(mode="json") for item in context.similar_cases[:5]
                    ],
                },
            )
            db.add(event)
            db.flush()
            summaries.append(
                RiskEventSummary(
                    event_id=event.event_id,
                    device_code=device.device_code,
                    event_type=event.event_type,
                    risk_level=event.risk_level,
                    risk_score=event.risk_score,
                    summary=event.summary,
                    evidence=event.evidence,
                    status=event.status,
                    report_id=event.report_id,
                    created_at=event.created_at,
                )
            )
    return summaries


def _event_type(abnormal_parameters: list[str], alarm_count: int) -> str:
    if alarm_count and abnormal_parameters:
        return "alarm_and_parameter_risk"
    if alarm_count:
        return "repeated_or_unresolved_alarm"
    if abnormal_parameters:
        return "parameter_degradation"
    return "risk_trend_change"


def _summary(device_code: str, health) -> str:
    parts = [f"{device_code} 风险等级为 {health.current_risk_level}"]
    if health.unresolved_alarm_count:
        parts.append(f"存在 {health.unresolved_alarm_count} 条未处理报警")
    if health.abnormal_parameters:
        parts.append(f"异常参数: {', '.join(health.abnormal_parameters)}")
    if health.trend == "worsening":
        parts.append("风险趋势正在上升")
    return "，".join(parts) + "。"
