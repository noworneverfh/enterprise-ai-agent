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