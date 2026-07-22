from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth import Permission, Role, User
from app.schemas.auth import CurrentUserResponse


ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": [
        "knowledge:upload",
        "knowledge:delete",
        "diagnosis:execute",
        "reports:view",
        "reports:view_all",
        "users:manage",
        "devices:view",
        "devices:write",
    ],
    "engineer": [
        "diagnosis:execute",
        "reports:view",
        "devices:view",
    ],
    "viewer": [
        "devices:view",
        "reports:view",
    ],
}

PERMISSION_DESCRIPTIONS = {
    "knowledge:upload": "Upload knowledge base documents.",
    "knowledge:delete": "Delete knowledge base documents.",
    "diagnosis:execute": "Run agent diagnosis and risk analysis.",
    "reports:view_all": "View all diagnosis reports.",
    "reports:view": "View diagnosis reports.",
    "users:manage": "Manage users and roles.",
    "devices:view": "View devices and runtime data.",
    "devices:write": "Create devices, runtime data, and alarms.",
}


def ensure_default_roles(db: Session) -> None:
    """Create default RBAC roles and permissions if they do not exist."""

    permissions_by_name: dict[str, Permission] = {}
    for permission_name, description in PERMISSION_DESCRIPTIONS.items():
        permission = db.scalar(
            select(Permission).where(Permission.name == permission_name)
        )
        if permission is None:
            permission = Permission(name=permission_name, description=description)
            db.add(permission)
            db.flush()
        permissions_by_name[permission_name] = permission

    for role_name, permission_names in ROLE_PERMISSIONS.items():
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(name=role_name, description=f"{role_name} role")
            db.add(role)
            db.flush()

        role.permissions = [permissions_by_name[name] for name in permission_names]

    db.commit()


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    role_name: str = "viewer",
) -> User:
    existing = get_user_by_username(db, username)
    if existing is not None:
        raise ValueError("username already exists")

    role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        raise ValueError("role does not exist")

    user = User(
        username=username,
        password_hash=hash_password(password),
        roles=[role],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(
    db: Session,
    *,
    username: str,
    password: str,
) -> User | None:
    user = get_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    if user.status != "active":
        return None
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.strip().lower()))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def user_permissions(user: User) -> list[str]:
    permissions: list[str] = []
    for role in user.roles:
        for permission in role.permissions:
            if permission.name not in permissions:
                permissions.append(permission.name)
    return permissions


def user_roles(user: User) -> list[str]:
    return [role.name for role in user.roles]


def to_current_user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        roles=user_roles(user),
        permissions=user_permissions(user),
        created_at=user.created_at,
    )
