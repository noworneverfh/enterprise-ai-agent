from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.context.device_context import build_device_context
from app.context.maintenance_memory import create_maintenance_record, list_maintenance_records
from app.context.risk_monitoring import scan_device_risks
from app.context.schemas import (
    DeviceContext,
    MaintenanceRecordCreate,
    RiskEventSummary,
)
from app.db.session import get_db
from app.models.auth import User
from app.services.audit import record_audit_event


router = APIRouter(tags=["Context Intelligence"])


@router.get("/devices/{device_code}/context", response_model=DeviceContext)
def get_device_context(
    device_code: str,
    _current_user: User | None = Depends(require_permission("devices:view")),
    db: Session = Depends(get_db),
) -> DeviceContext:
    context = build_device_context(db, device_code.strip().upper())
    if not context.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device context not found.",
        )
    return context


@router.post("/maintenance/records", status_code=status.HTTP_201_CREATED)
def save_maintenance_memory(
    payload: MaintenanceRecordCreate,
    current_user: User | None = Depends(require_permission("diagnosis:execute")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        record = create_maintenance_record(
            db,
            payload,
            performed_by=current_user.id if current_user else None,
        )
        db.commit()
        db.refresh(record)
        record_audit_event(
            db,
            action="maintenance.create",
            resource_type="maintenance_record",
            resource_id=str(record.id),
            result="success",
            user=current_user,
            detail={"device_code": payload.device_code, "resolved": payload.resolved},
        )
        return {
            "id": record.id,
            "device_id": record.device_id,
            "report_id": record.report_id,
            "resolved": record.resolved,
            "created_at": record.created_at,
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Maintenance memory save failed.",
        ) from exc


@router.get("/maintenance/records")
def get_maintenance_memory(
    device_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _current_user: User | None = Depends(require_permission("reports:view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    records = list_maintenance_records(db, device_code=device_code, limit=limit)
    return [
        {
            "id": record.id,
            "device_id": record.device_id,
            "report_id": record.report_id,
            "actual_action": record.actual_action,
            "confirmed_root_cause": record.confirmed_root_cause,
            "resolved": record.resolved,
            "result": record.result,
            "performed_at": record.performed_at,
            "created_at": record.created_at,
        }
        for record in records
    ]


@router.post("/agent/risk-monitoring/scan", response_model=list[RiskEventSummary])
def scan_risk_events(
    current_user: User | None = Depends(require_permission("diagnosis:execute")),
    db: Session = Depends(get_db),
) -> list[RiskEventSummary]:
    events = scan_device_risks(db)
    db.commit()
    record_audit_event(
        db,
        action="risk.scan",
        resource_type="risk_event",
        result="success",
        user=current_user,
        detail={"event_count": len(events)},
    )
    return events
