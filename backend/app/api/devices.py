from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.alarm import DeviceAlarmRecord
from app.models.device import Device
from app.models.runtime import DeviceRuntimeData
from app.schemas.device import (
    AlarmRecordCreate,
    AlarmRecordResponse,
    DeviceCreate,
    DeviceResponse,
    DeviceStatusResponse,
    RuntimeDataCreate,
    RuntimeDataResponse,
)
from app.services import device as device_service


router = APIRouter(
    prefix="/devices",
    tags=["Devices"],
)


@router.post(
    "",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_device(
    device_data: DeviceCreate,
    db: Session = Depends(get_db),
) -> Device:
    existing_device = device_service.get_device_by_code(db, device_data.device_code)

    if existing_device is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device code already exists.",
        )

    return device_service.create_device(db, device_data)


@router.get(
    "",
    response_model=list[DeviceResponse],
)
def list_devices(
    db: Session = Depends(get_db),
) -> list[Device]:
    return device_service.list_devices(db)


@router.get(
    "/{device_code}",
    response_model=DeviceResponse,
)
def get_device(
    device_code: str,
    db: Session = Depends(get_db),
) -> Device:
    device = _get_device_or_404(db, device_code)
    return device


@router.post(
    "/{device_code}/runtime-data",
    response_model=RuntimeDataResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_runtime_data(
    device_code: str,
    runtime_data: RuntimeDataCreate,
    db: Session = Depends(get_db),
) -> DeviceRuntimeData:
    device = _get_device_or_404(db, device_code)
    return device_service.create_runtime_data(db, device, runtime_data)


@router.get(
    "/{device_code}/runtime-data",
    response_model=list[RuntimeDataResponse],
)
def list_runtime_data(
    device_code: str,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[DeviceRuntimeData]:
    device = _get_device_or_404(db, device_code)
    return device_service.list_runtime_data(db, device, limit)


@router.get(
    "/{device_code}/status",
    response_model=DeviceStatusResponse,
)
def get_device_status(
    device_code: str,
    alarm_limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    device = _get_device_or_404(db, device_code)
    latest_runtime_data = device_service.get_latest_runtime_data(db, device)
    recent_alarms = device_service.list_alarm_records(
        db,
        device,
        limit=alarm_limit,
        is_resolved=False,
    )

    return {
        "device": device,
        "latest_runtime_data": latest_runtime_data,
        "recent_alarms": recent_alarms,
    }


@router.post(
    "/{device_code}/alarms",
    response_model=AlarmRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_alarm_record(
    device_code: str,
    alarm_data: AlarmRecordCreate,
    db: Session = Depends(get_db),
) -> DeviceAlarmRecord:
    device = _get_device_or_404(db, device_code)
    return device_service.create_alarm_record(db, device, alarm_data)


@router.get(
    "/{device_code}/alarms",
    response_model=list[AlarmRecordResponse],
)
def list_alarm_records(
    device_code: str,
    limit: int = Query(default=20, ge=1, le=200),
    is_resolved: bool | None = None,
    db: Session = Depends(get_db),
) -> list[DeviceAlarmRecord]:
    device = _get_device_or_404(db, device_code)
    return device_service.list_alarm_records(db, device, limit, is_resolved)


def _get_device_or_404(db: Session, device_code: str) -> Device:
    device = device_service.get_device_by_code(db, device_code)

    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )

    return device
