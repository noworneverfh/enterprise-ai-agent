from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal[
    "normal",
    "low",
    "medium",
    "high",
    "critical",
    "unknown",
]
EvidenceStatus = Literal["normal", "warning", "critical", "unknown", "info"]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]
ActionPriority = Literal["immediate", "planned", "observe"]
GenerationMode = Literal["llm", "mock", "fallback", "deterministic"]


class ConfirmedFact(BaseModel):
    """One fact copied from a trusted tool or deterministic rule."""

    fact_id: str
    category: Literal["device", "runtime", "alarm", "knowledge", "history"]
    label: str
    value: str
    status: EvidenceStatus = "info"
    source: str


class ParameterObservation(BaseModel):
    """Normalized runtime parameter and its model-aware operating range."""

    parameter: str
    label: str
    value: float
    unit: str
    normal_min: float
    normal_max: float
    status: EvidenceStatus
    explanation: str
    observed_at: datetime | None = None


class DiagnosisCause(BaseModel):
    """Possible cause that remains explicitly separate from confirmed facts."""

    title: str
    description: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)
    verification_method: str


class VerificationStep(BaseModel):
    """Manual verification needed before accepting a possible cause."""

    order: int = Field(ge=1)
    title: str
    description: str
    safety_note: str | None = None


class MaintenanceAction(BaseModel):
    """Prioritized maintenance action for field personnel."""

    order: int = Field(ge=1)
    priority: ActionPriority
    title: str
    description: str
    safety_required: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class DiagnosisCitation(BaseModel):
    """Traceable document evidence used by the diagnosis."""

    citation_id: str
    source: str
    title: str
    excerpt: str | None = None
    document_id: int | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None
    distance: float | None = None


class RiskScoreItem(BaseModel):
    """One explainable contribution to a deterministic risk score."""

    code: str
    label: str
    score: int
    reason: str


class RiskAssessment(BaseModel):
    """Risk level with a transparent, bounded score."""

    level: RiskLevel
    score: int = Field(ge=0, le=100)
    breakdown: list[RiskScoreItem] = Field(default_factory=list)


class DiagnosisReportV2(BaseModel):
    """Enterprise diagnosis report added without removing legacy fields."""

    report_version: Literal["2.0"] = "2.0"
    generation_mode: GenerationMode
    conclusion: str
    risk: RiskAssessment
    confirmed_facts: list[ConfirmedFact] = Field(default_factory=list)
    parameter_observations: list[ParameterObservation] = Field(default_factory=list)
    possible_causes: list[DiagnosisCause] = Field(default_factory=list)
    verification_steps: list[VerificationStep] = Field(default_factory=list)
    action_plan: list[MaintenanceAction] = Field(default_factory=list)
    citations: list[DiagnosisCitation] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    device_context_summary: dict | None = None
    risk_trend: list[dict] = Field(default_factory=list)
    historical_cases: list[dict] = Field(default_factory=list)
    maintenance_memory_refs: list[dict] = Field(default_factory=list)
    diagnosis_session_id: str | None = None


class DeviceRiskSummaryV2(BaseModel):
    """One device in a fleet risk report using the shared domain language."""

    device_code: str
    device_name: str
    device_type: str
    risk: RiskAssessment
    confirmed_facts: list[ConfirmedFact] = Field(default_factory=list)
    parameter_observations: list[ParameterObservation] = Field(default_factory=list)
    possible_causes: list[DiagnosisCause] = Field(default_factory=list)
    action_plan: list[MaintenanceAction] = Field(default_factory=list)
    citations: list[DiagnosisCitation] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    device_context_summary: dict | None = None
    risk_trend: list[dict] = Field(default_factory=list)
    historical_cases: list[dict] = Field(default_factory=list)
    maintenance_memory_refs: list[dict] = Field(default_factory=list)


class FleetRiskReportV2(BaseModel):
    """Structured enterprise report for multi-device risk analysis."""

    report_version: Literal["2.0"] = "2.0"
    generation_mode: GenerationMode
    summary: str
    overall_risk: RiskAssessment
    devices: list[DeviceRiskSummaryV2] = Field(default_factory=list)
    citations: list[DiagnosisCitation] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    diagnosis_session_id: str | None = None
