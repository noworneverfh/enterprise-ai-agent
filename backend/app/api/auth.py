from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.auth import User
from app.schemas.auth import (
    CurrentUserResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.services import auth as auth_service
from app.services.audit import record_audit_event


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: UserRegisterRequest,
    db: Session = Depends(get_db),
) -> CurrentUserResponse:
    if request.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration cannot create admin users.",
        )
    if request.role == "engineer" and not settings.public_engineer_registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public engineer registration is disabled.",
        )

    auth_service.ensure_default_roles(db)
    try:
        user = auth_service.create_user(
            db,
            username=request.username,
            password=request.password,
            role_name=request.role,
        )
    except ValueError as exc:
        record_audit_event(
            db,
            action="auth.register",
            resource_type="user",
            result="failed",
            detail={"username": request.username, "reason": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    record_audit_event(
        db,
        action="auth.register",
        resource_type="user",
        resource_id=str(user.id),
        result="success",
        user=user,
    )
    return auth_service.to_current_user_response(user)


@router.post("/login", response_model=TokenResponse)
def login(
    request: UserLoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = auth_service.authenticate_user(
        db,
        username=request.username,
        password=request.password,
    )
    if user is None:
        record_audit_event(
            db,
            action="auth.login",
            resource_type="user",
            result="failed",
            detail={"username": request.username},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    record_audit_event(
        db,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        result="success",
        user=user,
    )
    return TokenResponse(access_token=auth_service.create_access_token(user))


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return auth_service.to_current_user_response(current_user)
