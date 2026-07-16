from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceStatusToolInput(BaseModel):
    """Input for the deterministic device status tool."""

    device_code: str
    alarm_limit: int = Field(default=5, ge=1, le=20)

    @field_validator("device_code")
    @classmethod
    def normalize_device_code(cls, device_code: str) -> str:
        normalized = device_code.strip().upper()

        if not normalized:
            raise ValueError("device_code must not be empty.")

        if not normalized.startswith("DEV-") or not normalized[4:].isdigit():
            raise ValueError("device_code must match DEV-<number>.")

        return normalized


class ToolDeviceInfo(BaseModel):
    """Device information returned by an agent tool."""

    id: int
    device_code: str
    name: str
    device_type: str
    location: str | None
    is_online: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolRuntimeData(BaseModel):
    """Latest device runtime data returned by an agent tool."""

    id: int
    device_id: int
    temperature: float | None
    voltage: float | None
    current: float | None
    vibration: float | None
    status: str
    recorded_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolAlarmRecord(BaseModel):
    """Device alarm record returned by an agent tool."""

    id: int
    device_id: int
    alarm_code: str
    alarm_level: str
    message: str
    is_resolved: bool
    occurred_at: datetime
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeviceStatusToolResult(BaseModel):
    """Result returned by the deterministic device status tool."""

    ok: bool
    error_code: str | None = None
    device_exists: bool | None
    device: ToolDeviceInfo | None = None
    latest_runtime_data: ToolRuntimeData | None = None
    recent_alarms: list[ToolAlarmRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KnowledgeSearchToolInput(BaseModel):
    """Input for the deterministic knowledge search tool."""

    query: str
    top_k: int = Field(default=5, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, query: str) -> str:
        normalized = query.strip()

        if not normalized:
            raise ValueError("query must not be empty.")

        return normalized


class ToolKnowledgeResult(BaseModel):
    """Knowledge search hit returned by an agent tool."""

    chunk_id: int
    document_id: int
    filename: str
    chunk_index: int
    content: str
    source: str
    distance: float

    model_config = ConfigDict(from_attributes=True)


class KnowledgeSearchToolResult(BaseModel):
    """Result returned by the deterministic knowledge search tool."""

    ok: bool
    error_code: str | None = None
    results: list[ToolKnowledgeResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
