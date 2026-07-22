from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.agent import (
    DeviceAlarmsToolResult,
    DeviceStatusToolResult,
    KnowledgeSearchToolResult,
)
from app.context.schemas import DeviceContext


OrchestratorMode = Literal["runtime", "workflow", "multi_device"]
ToolStatus = Literal["success", "failed", "skipped"]
EvidenceKind = Literal["device", "alarm", "runtime", "knowledge", "history"]
GenerationProvider = Literal["mock", "openai", "ollama", "openai_compatible", "unknown"]
GenerationMode = Literal["production", "fallback", "mock"]


class EvidenceItem(BaseModel):
    """Trusted fact or document evidence produced before LLM reasoning."""

    kind: EvidenceKind
    source: str
    timestamp: datetime
    confidence: float = Field(ge=0, le=1)
    content: dict[str, Any] | str


class DiagnosisEvidenceBundle(BaseModel):
    """Normalized evidence boundary between tools/rules and the LLM."""

    device_facts: list[EvidenceItem] = Field(default_factory=list)
    alarm_facts: list[EvidenceItem] = Field(default_factory=list)
    parameter_observations: list[EvidenceItem] = Field(default_factory=list)
    knowledge_evidence: list[EvidenceItem] = Field(default_factory=list)
    history_cases: list[EvidenceItem] = Field(default_factory=list)

    def has_evidence(self) -> bool:
        return any(
            (
                self.device_facts,
                self.alarm_facts,
                self.parameter_observations,
                self.knowledge_evidence,
                self.history_cases,
            )
        )

    def sources(self) -> list[str]:
        sources: list[str] = []
        for item in self.knowledge_evidence:
            source = item.source
            if source and source not in sources:
                sources.append(source)
        return sources


class ToolExecutionRecord(BaseModel):
    """One tool execution with stable status and sanitized result."""

    tool_name: str
    status: ToolStatus
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    started_at: datetime
    finished_at: datetime
    duration_ms: int


class DiagnosisTrace(BaseModel):
    """Request-scoped trace that avoids relying on global latest trace state."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    device_id: str | None = None
    report_id: str | None = None
    mode: OrchestratorMode
    steps: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_step(self, name: str, status: str, detail: dict[str, Any] | None = None) -> None:
        self.steps.append(
            {
                "name": name,
                "status": status,
                "detail": detail or {},
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )


class GenerationMetadata(BaseModel):
    """Where and how the final language draft was produced."""

    provider: GenerationProvider = "unknown"
    mode: GenerationMode = "production"
    model: str | None = None
    request_id: str | None = None
    response_id: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    fallback_occurred: bool = False
    error_type: str | None = None


class DiagnosisOrchestratorContext(BaseModel):
    """Complete orchestration state for one request."""

    mode: OrchestratorMode
    query: str
    device_code: str | None = None
    planned_tools: list[str] = Field(default_factory=list)
    tool_records: list[ToolExecutionRecord] = Field(default_factory=list)
    device_context: DeviceContext | None = None
    evidence: DiagnosisEvidenceBundle = Field(default_factory=DiagnosisEvidenceBundle)
    trace: DiagnosisTrace
    generation_metadata: GenerationMetadata = Field(default_factory=GenerationMetadata)
    warnings: list[str] = Field(default_factory=list)

    def add_warning(self, warning: str) -> None:
        if warning and warning not in self.warnings:
            self.warnings.append(warning)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
