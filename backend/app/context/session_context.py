from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.context.schemas import DiagnosisSessionCreate
from app.models.context import DiagnosisSession


def persist_diagnosis_session(
    db: Session,
    data: DiagnosisSessionCreate,
) -> DiagnosisSession:
    """Persist one business diagnosis session."""

    session = DiagnosisSession(
        request_id=data.request_id,
        user_id=data.user_id,
        device_id=data.device_id,
        report_id=data.report_id,
        query=data.query,
        intent=data.intent,
        planned_tools=list(data.planned_tools),
        evidence_summary=_json_safe(data.evidence_summary),
        rag_summary=_json_safe(data.rag_summary),
        risk_summary=_json_safe(data.risk_summary),
        report_summary=_json_safe(data.report_summary),
        feedback_summary=_json_safe(data.feedback_summary),
        status=data.status,
    )
    db.add(session)
    return session


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)
