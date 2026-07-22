import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.api import agent as agent_api  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.llm.factory import get_llm_provider  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.agent import AgentDiagnoseResponse  # noqa: E402
from app.services import auth as auth_service  # noqa: E402
from app.models.diagnosis import AuditLog, LLMInvocation  # noqa: E402


@pytest.fixture
def rbac_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
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
    monkeypatch.setattr(settings, "public_engineer_registration_enabled", True)
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr("test-secret-key-with-at-least-32-bytes"),
    )
    monkeypatch.setattr(settings, "agent_runtime_enabled", False)
    monkeypatch.setattr(agent_api, "run_agent_diagnosis", _fake_diagnosis)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: object()

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        monkeypatch.setattr(settings, "auth_enabled", False)


def test_viewer_cannot_upload_knowledge_document(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "viewer01", "viewer")

    response = rbac_client.post(
        "/knowledge/documents",
        files={"file": ("manual.md", b"# Manual", "text/markdown")},
        headers=_auth_header(token),
    )

    assert response.status_code == 403


def test_viewer_cannot_delete_knowledge_document(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "viewer02", "viewer")

    response = rbac_client.delete(
        "/knowledge/documents/1",
        headers=_auth_header(token),
    )

    assert response.status_code == 403


def test_engineer_cannot_delete_knowledge_document(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "engineer01", "engineer")

    response = rbac_client.delete(
        "/knowledge/documents/1",
        headers=_auth_header(token),
    )

    assert response.status_code == 403


def test_admin_can_access_protected_device_query(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin01")

    response = rbac_client.get("/devices", headers=_auth_header(token))

    assert response.status_code == 200
    assert response.json() == []


def test_admin_receives_complete_permission_set(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin02")

    response = rbac_client.get("/auth/me", headers=_auth_header(token))

    assert response.status_code == 200
    assert set(response.json()["permissions"]) == set(
        auth_service.ROLE_PERMISSIONS["admin"]
    )


def test_viewer_cannot_access_admin_console(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "viewer_admin_console", "viewer")

    response = rbac_client.get(
        "/admin/console/overview",
        headers=_auth_header(token),
    )

    assert response.status_code == 403


def test_admin_can_access_admin_console_overview(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_console")

    response = rbac_client.get(
        "/admin/console/overview",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"]
    assert payload["core_services"]["total"] == 4


def test_admin_console_llm_metrics_aggregate_real_tokens(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_llm_metrics")
    with _client_db() as db:
        db.add(
            LLMInvocation(
                provider="openai_compatible",
                model="deepseek-chat",
                generation_mode="real",
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                latency_ms=1500,
                status="success",
                purpose="business",
            )
        )
        db.add(
            LLMInvocation(
                provider="mock",
                model="mock",
                generation_mode="mock",
                prompt_tokens=999,
                completion_tokens=999,
                total_tokens=1998,
                latency_ms=1,
                status="success",
                purpose="business",
            )
        )
        db.add(
            LLMInvocation(
                provider="openai_compatible",
                model="deepseek-chat",
                generation_mode="real",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                latency_ms=500,
                status="failed",
                purpose="business",
                error_type="TransportError",
            )
        )
        db.commit()

    response = rbac_client.get("/admin/console/llm", headers=_auth_header(token))

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["today_calls"] == 2
    assert metrics["today_prompt_tokens"] == 110
    assert metrics["today_completion_tokens"] == 25
    assert metrics["today_total_tokens"] == 135
    assert metrics["failure_count"] == 1


def test_admin_console_audit_filters(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_audit")
    with _client_db() as db:
        db.add_all(
            [
                AuditLog(
                    username="admin01",
                    action="auth.login",
                    resource_type="user",
                    result="success",
                ),
                AuditLog(
                    username="admin01",
                    action="knowledge.upload",
                    resource_type="knowledge_document",
                    result="success",
                ),
                AuditLog(
                    username="operator01",
                    action="auth.login",
                    resource_type="user",
                    result="failed",
                ),
            ]
        )
        db.commit()

    event_types = rbac_client.get("/admin/console/audit/event-types", headers=_auth_header(token))
    assert event_types.status_code == 200
    assert {"value": "user_login", "label": "用户登录"} in event_types.json()

    response = rbac_client.get(
        "/admin/console/audit-logs?action_type=user_login&username= admin &result=success",
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert all(item["action"] == "auth.login" for item in payload["items"])
    assert all(item["result"] == "success" for item in payload["items"])
    assert all("admin" in (item["username"] or "") for item in payload["items"])

    empty_response = rbac_client.get(
        "/admin/console/audit-logs?action_type=llm_failed",
        headers=_auth_header(token),
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["items"] == []


def test_viewer_cannot_access_admin_audit_event_types(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "viewer_audit_types", "viewer")

    response = rbac_client.get(
        "/admin/console/audit/event-types",
        headers=_auth_header(token),
    )

    assert response.status_code == 403


def test_admin_can_update_user_role_from_console(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_role_editor")
    _register_and_login(rbac_client, "role_target", "viewer")

    users_response = rbac_client.get(
        "/admin/console/permissions",
        headers=_auth_header(token),
    )
    target = next(user for user in users_response.json()["users"] if user["username"] == "role_target")

    response = rbac_client.patch(
        f"/admin/console/users/{target['id']}/role",
        json={"role": "Admin"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["roles"] == ["Admin"]

    me_response = rbac_client.post(
        "/auth/login",
        json={"username": "role_target", "password": "secret123"},
    )
    assert me_response.status_code == 200
    target_token = me_response.json()["access_token"]
    assert "users:manage" in rbac_client.get("/auth/me", headers=_auth_header(target_token)).json()["permissions"]


def test_admin_can_delete_unused_user_from_console(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_user_deleter")
    _register_and_login(rbac_client, "unused_user", "viewer")

    users_response = rbac_client.get(
        "/admin/console/permissions",
        headers=_auth_header(token),
    )
    target = next(user for user in users_response.json()["users"] if user["username"] == "unused_user")

    response = rbac_client.delete(
        f"/admin/console/users/{target['id']}",
        headers=_auth_header(token),
    )

    assert response.status_code == 204
    assert rbac_client.post(
        "/auth/login",
        json={"username": "unused_user", "password": "secret123"},
    ).status_code == 401


def test_admin_cannot_delete_current_account(rbac_client: TestClient) -> None:
    token = _create_admin_and_login(rbac_client, "admin_keep_self")

    users_response = rbac_client.get(
        "/admin/console/permissions",
        headers=_auth_header(token),
    )
    current = next(user for user in users_response.json()["users"] if user["username"] == "admin_keep_self")

    response = rbac_client.delete(
        f"/admin/console/users/{current['id']}",
        headers=_auth_header(token),
    )

    assert response.status_code == 400


def test_engineer_can_execute_diagnosis(rbac_client: TestClient) -> None:
    token = _register_and_login(rbac_client, "engineer02", "engineer")

    response = rbac_client.post(
        "/agent/diagnose",
        json={
            "query": "分析设备异常",
            "device_code": "DEV-001",
            "knowledge_top_k": 5,
            "include_device_status": True,
            "include_knowledge": True,
        },
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["problem_summary"] == "RBAC diagnosis allowed."


def _register_and_login(client: TestClient, username: str, role: str) -> str:
    password = "secret123"
    register_response = client.post(
        "/auth/register",
        json={"username": username, "password": password, "role": role},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def _create_admin_and_login(client: TestClient, username: str) -> str:
    password = "secret123"
    with _client_db() as db:
        auth_service.ensure_default_roles(db)
        auth_service.create_user(
            db,
            username=username,
            password=password,
            role_name="admin",
        )

    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _client_db:
    def __enter__(self) -> Session:
        override = app.dependency_overrides[get_db]
        self.generator = override()
        self.db = next(self.generator)
        return self.db

    def __exit__(self, *args: object) -> None:
        self.db.close()


def _fake_diagnosis(*args: object, **kwargs: object) -> AgentDiagnoseResponse:
    return AgentDiagnoseResponse(
        problem_summary="RBAC diagnosis allowed.",
        device=None,
        device_status=None,
        recent_alarms=[],
        risk_level="unknown",
        possible_causes=[],
        recommended_actions=["Continue with authorized diagnosis."],
        sources=[],
        tools_used=[],
        warnings=[],
        disclaimer="Test response.",
    )
