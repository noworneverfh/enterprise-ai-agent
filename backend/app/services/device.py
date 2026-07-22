from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.alarm import DeviceAlarmRecord
from app.models.device import Device
from app.models.runtime import DeviceRuntimeData
from app.schemas.device import (
    AlarmRecordCreate,
    DeviceCreate,
    RuntimeDataCreate,
)


def get_device_by_code(db: Session, device_code: str) -> Device | None:
    """Return one device by its business code."""

    return db.scalar(select(Device).where(Device.device_code == device_code))


def list_devices(db: Session) -> list[Device]:
    """Return all devices ordered by primary key."""

    return list(db.scalars(select(Device).order_by(Device.id)).all())


def get_device_statistics(db: Session) -> dict[str, int]:
    """Return dashboard-grade status counts derived from persisted device data.

    The current schema stores the operational state in the latest runtime data
    rather than on the device record itself. For dashboard purposes we classify
    each device once, using the latest known runtime status and online flag.
    """

    stats = {
        "total": 0,
        "normal": 0,
        "warning": 0,
        "maintenance": 0,
    }

    for device in list_devices(db):
        stats["total"] += 1
        latest_runtime_data = get_latest_runtime_data(db, device)
        status = (latest_runtime_data.status if latest_runtime_data else "").lower()

        if not device.is_online or status in {"maintenance", "maintaining", "offline"}:
            stats["maintenance"] += 1
        elif status in {"warning", "critical", "danger", "error", "abnormal"}:
            stats["warning"] += 1
        else:
            stats["normal"] += 1

    return stats


def create_device(db: Session, device_data: DeviceCreate) -> Device:
    """Create one device record."""

    device = Device(**device_data.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def create_runtime_data(
    db: Session,
    device: Device,
    runtime_data: RuntimeDataCreate,
) -> DeviceRuntimeData:
    """Create one runtime metric record for a device."""

    data = runtime_data.model_dump()
    if data["recorded_at"] is None:
        data["recorded_at"] = datetime.utcnow()

    record = DeviceRuntimeData(device_id=device.id, **data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_runtime_data(
    db: Session,
    device: Device,
    limit: int,
) -> list[DeviceRuntimeData]:
    """Return recent runtime data for one device."""

    query = (
        select(DeviceRuntimeData)
        .where(DeviceRuntimeData.device_id == device.id)
        .order_by(DeviceRuntimeData.recorded_at.desc(), DeviceRuntimeData.id.desc())
        .limit(limit)
    )
    return list(db.scalars(query).all())


def get_latest_runtime_data(
    db: Session,
    device: Device,
) -> DeviceRuntimeData | None:
    """Return the latest runtime data point for one device."""

    return db.scalar(
        select(DeviceRuntimeData)
        .where(DeviceRuntimeData.device_id == device.id)
        .order_by(DeviceRuntimeData.recorded_at.desc(), DeviceRuntimeData.id.desc())
        .limit(1)
    )


def create_alarm_record(
    db: Session,
    device: Device,
    alarm_data: AlarmRecordCreate,
) -> DeviceAlarmRecord:
    """Create one alarm record for a device."""

    data = alarm_data.model_dump()
    if data["occurred_at"] is None:
        data["occurred_at"] = datetime.utcnow()

    record = DeviceAlarmRecord(device_id=device.id, **data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_alarm_records(
    db: Session,
    device: Device,
    limit: int,
    is_resolved: bool | None = None,
) -> list[DeviceAlarmRecord]:
    """Return recent alarm records for one device."""

    query: Select[tuple[DeviceAlarmRecord]] = select(DeviceAlarmRecord).where(
        DeviceAlarmRecord.device_id == device.id
    )

    if is_resolved is not None:
        query = query.where(DeviceAlarmRecord.is_resolved == is_resolved)

    query = query.order_by(
        DeviceAlarmRecord.occurred_at.desc(),
        DeviceAlarmRecord.id.desc(),
    ).limit(limit)

    return list(db.scalars(query).all())


def list_recent_alarm_records(
    db: Session,
    limit: int = 20,
    device_code: str | None = None,
    is_resolved: bool | None = None,
) -> list[DeviceAlarmRecord]:
    """Return recent alarm records across devices or for one device."""

    query: Select[tuple[DeviceAlarmRecord]] = select(DeviceAlarmRecord).join(
        Device,
        Device.id == DeviceAlarmRecord.device_id,
    )

    if device_code is not None:
        query = query.where(Device.device_code == device_code)

    if is_resolved is not None:
        query = query.where(DeviceAlarmRecord.is_resolved == is_resolved)

    query = query.order_by(
        DeviceAlarmRecord.occurred_at.desc(),
        DeviceAlarmRecord.id.desc(),
    ).limit(limit)

    return list(db.scalars(query).all())
