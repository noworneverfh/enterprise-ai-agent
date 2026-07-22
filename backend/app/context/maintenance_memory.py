from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.schemas import MaintenanceRecordCreate
from app.models.alarm import DeviceAlarmRecord
from app.models.context import MaintenanceRecord
from app.models.knowledge_structured import FaultKnowledgeEntry, MaintenanceCase
from app.services import device as device_service


def create_maintenance_record(
    db: Session,
    data: MaintenanceRecordCreate,
    *,
    performed_by: int | None = None,
) -> MaintenanceRecord:
    """Save field maintenance feedback and turn resolved work into a reusable case."""

    device = device_service.get_device_by_code(db, data.device_code)
    if device is None:
        raise ValueError(f"Device not found: {data.device_code}")

    record = MaintenanceRecord(
        device_id=device.id,
        alarm_record_id=data.alarm_record_id,
        report_id=data.report_id,
        ai_recommendation=data.ai_recommendation,
        actual_action=data.actual_action,
        confirmed_root_cause=data.confirmed_root_cause,
        resolved=data.resolved,
        result=data.result,
        performed_by=performed_by,
        performed_at=data.performed_at,
    )
    db.add(record)
    db.flush()
    if record.resolved and record.confirmed_root_cause:
        _upsert_case_from_record(db, record)
    return record


def list_maintenance_records(
    db: Session,
    *,
    device_code: str | None = None,
    limit: int = 20,
) -> list[MaintenanceRecord]:
    query = select(MaintenanceRecord).order_by(
        MaintenanceRecord.created_at.desc(),
        MaintenanceRecord.id.desc(),
    )
    if device_code:
        device = device_service.get_device_by_code(db, device_code)
        if device is None:
            return []
        query = query.where(MaintenanceRecord.device_id == device.id)
    return list(db.scalars(query.limit(limit)).all())


def _upsert_case_from_record(db: Session, record: MaintenanceRecord) -> None:
    alarm = (
        db.get(DeviceAlarmRecord, record.alarm_record_id)
        if record.alarm_record_id is not None
        else None
    )
    device_code = None
    if alarm is not None and alarm.device is not None:
        device_code = alarm.device.device_code
    if device_code is None:
        from app.models.device import Device

        loaded_device = db.get(Device, record.device_id)
        device_code = loaded_device.device_code if loaded_device is not None else "UNKNOWN"

    fault_code = alarm.alarm_code if alarm is not None else "UNKNOWN"
    entry = db.scalar(
        select(FaultKnowledgeEntry).where(FaultKnowledgeEntry.fault_code == fault_code)
    )
    existing = db.scalar(
        select(MaintenanceCase)
        .where(MaintenanceCase.device == device_code)
        .where(MaintenanceCase.fault == fault_code)
        .where(MaintenanceCase.root_cause == record.confirmed_root_cause)
    )
    if existing is not None:
        return
    db.add(
        MaintenanceCase(
            fault_entry_id=entry.id if entry is not None else None,
            device=device_code,
            fault=fault_code,
            symptom=alarm.message if alarm is not None else "现场维修反馈",
            root_cause=record.confirmed_root_cause,
            solution=record.actual_action,
            result=record.result or ("故障已解决" if record.resolved else "处理结果待确认"),
        )
    )
