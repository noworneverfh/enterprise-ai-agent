from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    """Request body for creating a device."""

    device_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=50)
    location: str | None = Field(default=None, max_length=100)
    is_online: bool = False


class DeviceResponse(BaseModel):
    """Device data returned by the API."""

    id: int
    device_code: str
    name: str
    device_type: str
    location: str | None
    is_online: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuntimeDataCreate(BaseModel):
    """Request body for adding one runtime data point."""

    temperature: float | None = None
    voltage: float | None = None
    current: float | None = None
    vibration: float | None = None
    status: str = Field(default="normal", min_length=1, max_length=20)
    recorded_at: datetime | None = None


class RuntimeDataResponse(BaseModel):
    """Runtime data returned by the API."""

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


class AlarmRecordCreate(BaseModel):
    """Request body for adding one alarm record."""

    alarm_code: str = Field(min_length=1, max_length=50)
    alarm_level: str = Field(min_length=1, max_length=20)
    message: str = Field(min_length=1, max_length=255)
    is_resolved: bool = False
    occurred_at: datetime | None = None
    resolved_at: datetime | None = None


class AlarmRecordResponse(BaseModel):
    """Alarm record returned by the API."""

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


class DeviceStatusResponse(BaseModel):
    """Latest device status used by API users and future agent tools."""

    device: DeviceResponse
    latest_runtime_data: RuntimeDataResponse | None
    recent_alarms: list[AlarmRecordResponse]
