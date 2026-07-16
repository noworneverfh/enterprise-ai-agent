from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.device import Device
from app.schemas.device import DeviceCreate, DeviceResponse


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
    existing_device = db.scalar(
        select(Device).where(Device.device_code == device_data.device_code)
    )

    if existing_device is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device code already exists.",
        )

    device = Device(**device_data.model_dump())

    db.add(device)
    db.commit()
    db.refresh(device)

    return device


@router.get(
    "",
    response_model=list[DeviceResponse],
)
def list_devices(
    db: Session = Depends(get_db),
) -> list[Device]:
    devices = db.scalars(
        select(Device).order_by(Device.id)
    ).all()

    return list(devices)