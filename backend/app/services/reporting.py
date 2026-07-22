from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.diagnosis.models import DiagnosisReportV2, FleetRiskReportV2
from app.models.diagnosis import DiagnosisRecord, DiagnosisReport, DiagnosisTrace


def persist_report_v2(
    db: Session,
    *,
    record: DiagnosisRecord,
    report: DiagnosisReportV2 | FleetRiskReportV2 | None,
    trace: dict[str, Any] | None,
    provider_type: str | None = None,
    generation_status: str = "completed",
    user_id: int | None = None,
) -> None:
    """Persist structured Report V2 and trace rows beside legacy history."""

    if report is None:
        return

    report_payload = report.model_dump(mode="json")
    risk_payload = report_payload.get("risk") or report_payload.get("overall_risk") or {}
    risk_level = risk_payload.get("level") or record.risk_level
    risk_score = risk_payload.get("score")
    device_id = _extract_device_id(report_payload)

    db.add(
        DiagnosisReport(
            report_id=record.report_id,
            diagnosis_record_id=record.id,
            report_version=str(report_payload.get("report_version", "2.0")),
            device_id=device_id,
            risk_level=str(risk_level),
            risk_score=risk_score if isinstance(risk_score, int) else None,
            confirmed_facts=report_payload.get("confirmed_facts"),
            parameter_observations=report_payload.get("parameter_observations"),
            cause_analysis=report_payload.get("possible_causes"),
            verification_steps=report_payload.get("verification_steps"),
            action_plan=report_payload.get("action_plan"),
            citations=report_payload.get("citations"),
            provider_type=provider_type or str(report_payload.get("generation_mode", "unknown")),
            generation_status=generation_status,
            report_json=report_payload,
        )
    )
    _persist_trace_rows(db, record.report_id, trace, user_id=user_id)


def _persist_trace_rows(
    db: Session,
    report_id: str,
    trace: dict[str, Any] | None,
    *,
    user_id: int | None,
) -> None:
    if not isinstance(trace, dict):
        return

    request_id = str(trace.get("trace_id") or report_id)
    rows: list[DiagnosisTrace] = [
        DiagnosisTrace(
            request_id=request_id,
            user_id=user_id,
            report_id=report_id,
            step="router",
            tool_name=None,
            input_summary={"query": trace.get("query"), "device_code": trace.get("device_code")},
            output_summary={"tools": trace.get("router_tools", [])},
            duration_ms=None,
            status="completed",
        )
    ]

    for tool in trace.get("tool_results", []) if isinstance(trace.get("tool_results"), list) else []:
        if not isinstance(tool, dict):
            continue
        rows.append(
            DiagnosisTrace(
                request_id=request_id,
                user_id=user_id,
                report_id=report_id,
                step="tool",
                tool_name=tool.get("tool_name"),
                input_summary=None,
                output_summary=tool.get("result") if isinstance(tool.get("result"), dict) else {},
                duration_ms=None,
                status="completed" if tool.get("success") else "failed",
            )
        )

    llm_status = trace.get("llm_final_status") if isinstance(trace.get("llm_final_status"), dict) else {}
    rows.append(
        DiagnosisTrace(
            request_id=request_id,
            user_id=user_id,
            report_id=report_id,
            step="llm",
            tool_name=None,
            input_summary=None,
            output_summary=llm_status,
            duration_ms=None,
            status=str(llm_status.get("status") or "unknown"),
        )
    )
    db.add_all(rows)


def _extract_device_id(report_payload: dict[str, Any]) -> int | None:
    for fact in report_payload.get("confirmed_facts", []) or []:
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_id") == "device.id" and isinstance(fact.get("value"), int):
            return fact["value"]
    return None
