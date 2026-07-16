from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.alarm import DeviceAlarmRecord
    from app.models.runtime import DeviceRuntimeData


class Device(Base):
    """IoT device database model."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    device_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    runtime_data: Mapped[list["DeviceRuntimeData"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
    alarm_records: Mapped[list["DeviceAlarmRecord"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )
