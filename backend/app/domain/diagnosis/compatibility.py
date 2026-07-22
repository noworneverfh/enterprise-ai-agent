from collections.abc import Mapping
from typing import Any

from app.domain.diagnosis.report_builder import (
    build_fleet_risk_report,
    build_single_diagnosis_report,
)
from app.schemas.agent import (
    AgentDiagnoseResponse,
    MultiDeviceRiskResponse,
)


def attach_single_report_v2(
    response: AgentDiagnoseResponse,
    trace: Mapping[str, Any] | None = None,
) -> AgentDiagnoseResponse:
    """Add Report V2 while preserving every legacy response field."""

    report = build_single_diagnosis_report(
        response.model_dump(mode="python", exclude={"report_v2"}),
        trace,
    )
    return response.model_copy(update={"report_v2": report})


def attach_fleet_report_v2(
    response: MultiDeviceRiskResponse,
    trace: Mapping[str, Any] | None = None,
) -> MultiDeviceRiskResponse:
    """Add fleet Report V2 while preserving every legacy response field."""

    report = build_fleet_risk_report(
        response.model_dump(mode="python", exclude={"report_v2"}),
        trace,
    )
    return response.model_copy(update={"report_v2": report})
