from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DeviceContextDevice(BaseModel):
    id: int
    device_code: str
    name: str
    device_type: str
    location: str | None = None
    is_online: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceContextRuntimePoint(BaseModel):
    id: int
    temperature: float | None = None
    voltage: float | None = None
    current: float | None = None
    vibration: float | None = None
    status: str
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceContextAlarm(BaseModel):
    id: int
    alarm_code: str
    alarm_name: str
    alarm_level: str
    message: str
    is_resolved: bool
    occurred_at: datetime
    resolved_at: datetime | None = None


class DeviceContextDiagnosisHistory(BaseModel):
    report_id: str
    query: str
    risk_level: str
    problem_summary: str
    created_at: datetime


class DeviceContextRiskPoint(BaseModel):
    risk_level: str
    risk_score: int
    alarm_count: int
    abnormal_parameters: list[str] = Field(default_factory=list)
    report_id: str | None = None
    recorded_at: datetime


class DeviceContextMaintenanceMemory(BaseModel):
    id: int
    report_id: str | None = None
    alarm_code: str | None = None
    actual_action: str
    confirmed_root_cause: str | None = None
    resolved: bool
    result: str | None = None
    performed_at: datetime | None = None
    created_at: datetime


class DeviceContextKnowledgeLink(BaseModel):
    fault_code: str
    fault_name: str
    severity: str
    device_type: str | None = None
    document_id: int | None = None
    cause_count: int = 0
    case_count: int = 0


class DeviceContextSimilarCase(BaseModel):
    id: int
    device: str
    fault: str
    symptom: str
    root_cause: str
    solution: str
    result: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceHealthSummary(BaseModel):
    current_risk_level: str
    current_risk_score: int
    unresolved_alarm_count: int
    historical_alarm_count: int
    diagnosis_count: int
    maintenance_record_count: int
    abnormal_parameters: list[str] = Field(default_factory=list)
    trend: Literal["improving", "stable", "worsening", "unknown"] = "unknown"


class DeviceContext(BaseModel):
    """Long-term industrial context loaded before each diagnosis."""

    exists: bool
    device: DeviceContextDevice | None = None
    current_runtime: DeviceContextRuntimePoint | None = None
    runtime_history: list[DeviceContextRuntimePoint] = Field(default_factory=list)
    current_alarms: list[DeviceContextAlarm] = Field(default_factory=list)
    historical_alarms: list[DeviceContextAlarm] = Field(default_factory=list)
    diagnosis_history: list[DeviceContextDiagnosisHistory] = Field(default_factory=list)
    risk_trend: list[DeviceContextRiskPoint] = Field(default_factory=list)
    maintenance_memory: list[DeviceContextMaintenanceMemory] = Field(default_factory=list)
    related_knowledge: list[DeviceContextKnowledgeLink] = Field(default_factory=list)
    similar_cases: list[DeviceContextSimilarCase] = Field(default_factory=list)
    health_summary: DeviceHealthSummary | None = None

    def compact(self) -> dict[str, Any]:
        """Return a compact, prompt-safe profile for Agent/RAG context."""

        payload = self.model_dump(mode="json")
        payload["runtime_history"] = payload["runtime_history"][:5]
        payload["historical_alarms"] = payload["historical_alarms"][:10]
        payload["diagnosis_history"] = payload["diagnosis_history"][:5]
        payload["risk_trend"] = payload["risk_trend"][:10]
        payload["maintenance_memory"] = payload["maintenance_memory"][:5]
        payload["similar_cases"] = payload["similar_cases"][:5]
        return payload


class DiagnosisSessionCreate(BaseModel):
    query: str
    request_id: str | None = None
    user_id: int | None = None
    device_id: int | None = None
    report_id: str | None = None
    intent: str | None = None
    planned_tools: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    rag_summary: list[dict[str, Any]] = Field(default_factory=list)
    risk_summary: dict[str, Any] = Field(default_factory=dict)
    report_summary: dict[str, Any] = Field(default_factory=dict)
    feedback_summary: dict[str, Any] | None = None
    status: str = "completed"


class MaintenanceRecordCreate(BaseModel):
    device_code: str
    report_id: str | None = None
    alarm_record_id: int | None = None
    ai_recommendation: list[dict[str, Any]] | dict[str, Any] | None = None
    actual_action: str
    confirmed_root_cause: str | None = None
    resolved: bool = False
    result: str | None = None
    performed_at: datetime | None = None


class RiskEventSummary(BaseModel):
    event_id: str
    device_code: str
    event_type: str
    risk_level: str
    risk_score: int
    summary: str
    evidence: dict[str, Any] | list[dict[str, Any]] | None = None
    status: str
    report_id: str | None = None
    created_at: datetime
