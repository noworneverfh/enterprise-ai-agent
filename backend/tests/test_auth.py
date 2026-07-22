import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import User  # noqa: E402
from app.models.diagnosis import AuditLog  # noqa: E402
from app.services import auth as auth_service  # noqa: E402


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "public_engineer_registration_enabled", False)
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr("test-secret-key-with-at-least-32-bytes"),
    )
    monkeypatch.setattr(settings, "jwt_access_token_expire_minutes", 30)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        monkeypatch.setattr(settings, "auth_enabled", False)


def test_pyjwt_dependency_is_importable() -> None:
    assert jwt.__version__


def test_register_creates_viewer_with_hashed_password(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/register",
        json={"username": "Viewer01", "password": "secret123", "role": "viewer"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "viewer01"
    assert data["roles"] == ["viewer"]
    assert "devices:view" in data["permissions"]

    with _client_db(auth_client) as db:
        user = db.scalar(select(User).where(User.username == "viewer01"))
        assert user is not None
        assert user.password_hash != "secret123"
        assert auth_service.verify_password("secret123", user.password_hash)


def test_login_returns_token_and_me_validates_it(auth_client: TestClient) -> None:
    auth_client.post(
        "/auth/register",
        json={"username": "viewer01", "password": "secret123", "role": "viewer"},
    )

    login_response = auth_client.post(
        "/auth/login",
        json={"username": "viewer01", "password": "secret123"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    assert token

    me_response = auth_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["username"] == "viewer01"

    with _client_db(auth_client) as db:
        user = db.scalar(select(User).where(User.username == "viewer01"))
        audit_actions = [
            row.action
            for row in db.query(AuditLog).order_by(AuditLog.id).all()
        ]
        assert user is not None
        assert user.last_login_at is not None
        assert audit_actions == ["auth.register", "auth.login"]


def test_duplicate_username_is_rejected(auth_client: TestClient) -> None:
    payload = {"username": "viewer02", "password": "secret123", "role": "viewer"}

    assert auth_client.post("/auth/register", json=payload).status_code == 201
    assert auth_client.post("/auth/register", json=payload).status_code == 400


def test_public_registration_cannot_create_admin(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/register",
        json={"username": "admin01", "password": "secret123", "role": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Public registration cannot create admin users."


def test_public_engineer_registration_requires_configuration(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = auth_client.post(
        "/auth/register",
        json={"username": "engineer01", "password": "secret123", "role": "engineer"},
    )
    assert response.status_code == 403

    monkeypatch.setattr(settings, "public_engineer_registration_enabled", True)
    enabled_response = auth_client.post(
        "/auth/register",
        json={"username": "engineer01", "password": "secret123", "role": "engineer"},
    )
    assert enabled_response.status_code == 201


def test_wrong_password_returns_401(auth_client: TestClient) -> None:
    auth_client.post(
        "/auth/register",
        json={"username": "viewer03", "password": "secret123", "role": "viewer"},
    )

    response = auth_client.post(
        "/auth/login",
        json={"username": "viewer03", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_me_without_token_returns_401(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_auth_disabled_keeps_demo_device_queries_compatible(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "auth_enabled", False)

    response = auth_client.get("/devices")

    assert response.status_code == 200


class _client_db:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __enter__(self) -> Session:
        override = app.dependency_overrides[get_db]
        self.generator = override()
        self.db = next(self.generator)
        return self.db

    def __exit__(self, *args: object) -> None:
        self.db.close()
