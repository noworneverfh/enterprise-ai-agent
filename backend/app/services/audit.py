from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.diagnosis import AuditLog


logger = logging.getLogger(__name__)


def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    result: str,
    user: User | None = None,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist a best-effort audit event without interrupting business flow."""

    try:
        db.add(
            AuditLog(
                user_id=user.id if user is not None else None,
                username=user.username if user is not None else None,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                detail=detail or {},
            )
        )
        db.commit()
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        logger.exception("Failed to record audit event. action=%s", action)
