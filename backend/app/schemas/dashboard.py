from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.diagnosis.models import DiagnosisReportV2, FleetRiskReportV2
from app.schemas.agent import AgentDiagnoseResponse, MultiDeviceRiskResponse


class DashboardOverviewResponse(BaseModel):
    """Aggregated numbers for the frontend home dashboard."""

    online_devices: int
    today_diagnosis_count: int
    knowledge_documents_count: int
    agent_status: str
    avg_response_time: float | None


class RecentAlarmResponse(BaseModel):
    """Recent alarm summary used by the dashboard."""

    device_code: str
    alarm_code: str
    alarm_name: str
    alarm_level: str
    status: str
    created_at: datetime


class DiagnosisHistoryItem(BaseModel):
    """Diagnosis report summary shown in recent history."""

    report_id: str
    device_code: str | None
    alarm_code: str | None
    alarm_name: str | None
    risk_level: str
    status: str
    created_at: datetime
    confidence: int | None = None
    problem_summary: str | None = None
    sources: list[str] = []
    tools_used: list[str] = []


class DiagnosisRagSource(BaseModel):
    """RAG source persisted with a diagnosis report."""

    source: str
    filename: str | None = None
    chunk_id: int | None = None
    chunk_index: int | None = None
    distance: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None
    content: str | None = None


class DiagnosisHistoryDetail(BaseModel):
    """Full persisted diagnosis report for review."""

    report_id: str
    device_code: str | None
    alarm_code: str | None
    alarm_name: str | None
    risk_level: str
    status: str
    query: str
    problem_summary: str
    response: AgentDiagnoseResponse | None = None
    risk_report: MultiDeviceRiskResponse | None = None
    tools_used: list[str]
    rag_sources: list[DiagnosisRagSource]
    confidence: int | None
    duration_ms: int | None
    trace: dict[str, Any] | None = None
    report_v2: DiagnosisReportV2 | FleetRiskReportV2 | None = None
    created_at: datetime


class SystemHealthResponse(BaseModel):
    """Component-level agent health without exposing internal configuration."""

    router: str
    tools: str
    rag: str
    llm: str
