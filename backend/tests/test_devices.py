import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Device, DeviceAlarmRecord, DeviceRuntimeData  # noqa: E402,F401


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
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


def test_create_and_get_device(client: TestClient) -> None:
    response = client.post(
        "/devices",
        json={
            "device_code": "DEV-T01",
            "name": "Test Pump",
            "device_type": "pump",
            "location": "Lab A",
            "is_online": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["device_code"] == "DEV-T01"

    response = client.get("/devices/DEV-T01")

    assert response.status_code == 200
    assert response.json()["name"] == "Test Pump"


def test_runtime_alarm_and_status_flow(client: TestClient) -> None:
    client.post(
        "/devices",
        json={
            "device_code": "DEV-T02",
            "name": "Test Motor",
            "device_type": "motor",
            "location": "Lab B",
            "is_online": True,
        },
    )

    runtime_response = client.post(
        "/devices/DEV-T02/runtime-data",
        json={
            "temperature": 86.5,
            "voltage": 220.0,
            "current": 8.2,
            "vibration": 2.1,
            "status": "warning",
        },
    )
    alarm_response = client.post(
        "/devices/DEV-T02/alarms",
        json={
            "alarm_code": "E101",
            "alarm_level": "high",
            "message": "Temperature is above threshold.",
        },
    )

    assert runtime_response.status_code == 201
    assert alarm_response.status_code == 201

    status_response = client.get("/devices/DEV-T02/status")

    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["device"]["device_code"] == "DEV-T02"
    assert status_data["latest_runtime_data"]["status"] == "warning"
    assert status_data["recent_alarms"][0]["alarm_code"] == "E101"


def test_device_statistics_are_derived_from_latest_runtime_status(client: TestClient) -> None:
    devices = [
        ("DEV-N01", "Normal Pump", True, "normal"),
        ("DEV-N02", "Normal Fan", True, "normal"),
        ("DEV-W01", "Warning Motor", True, "warning"),
        ("DEV-M01", "Maintenance Compressor", True, "maintenance"),
        ("DEV-O01", "Offline Gateway", False, "normal"),
    ]

    for code, name, is_online, runtime_status in devices:
        create_response = client.post(
            "/devices",
            json={
                "device_code": code,
                "name": name,
                "device_type": "demo",
                "location": "Test Workshop",
                "is_online": is_online,
            },
        )
        assert create_response.status_code == 201
        runtime_response = client.post(
            f"/devices/{code}/runtime-data",
            json={
                "temperature": 35.0,
                "voltage": 230.0,
                "current": 4.0,
                "vibration": 0.1,
                "status": runtime_status,
            },
        )
        assert runtime_response.status_code == 201

    response = client.get("/devices/statistics")

    assert response.status_code == 200
    assert response.json() == {
        "total": 5,
        "normal": 2,
        "warning": 1,
        "maintenance": 2,
    }


def test_duplicate_device_code_returns_conflict(client: TestClient) -> None:
    payload = {
        "device_code": "DEV-T03",
        "name": "Duplicate Device",
        "device_type": "sensor",
        "location": "Lab C",
        "is_online": False,
    }

    first_response = client.post("/devices", json=payload)
    second_response = client.post("/devices", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
