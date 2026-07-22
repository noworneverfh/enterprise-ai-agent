from collections.abc import Generator
import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chunk import KnowledgeChunk  # noqa: E402
from app.models.document import KnowledgeDocument  # noqa: E402


def test_seed_demo_data_is_idempotent_and_queryable(monkeypatch) -> None:
    client, SessionLocal = _build_client()
    seed_module = _load_seed_module()
    monkeypatch.setattr(
        seed_module,
        "create_document_from_file",
        _fake_create_document_from_file,
    )
    monkeypatch.setattr(seed_module, "delete_document", _fake_delete_document)

    db = SessionLocal()
    try:
        first_result = seed_module.seed_demo_data(db)
        second_result = seed_module.seed_demo_data(db)
    finally:
        db.close()

    try:
        assert first_result == {
            "created_devices": 8,
            "created_runtime_rows": 8,
            "created_alarm_rows": 6,
            "created_knowledge_documents": 12,
            "refreshed_knowledge_documents": 0,
            "created_diagnosis_records": 6,
            "created_maintenance_records": 5,
            "created_risk_events": 6,
            "created_risk_points": 40,
            "created_structured_knowledge": 5,
        }
        assert second_result == {
            "created_devices": 0,
            "created_runtime_rows": 0,
            "created_alarm_rows": 0,
            "created_knowledge_documents": 0,
            "refreshed_knowledge_documents": 0,
            "created_diagnosis_records": 0,
            "created_maintenance_records": 0,
            "created_risk_events": 0,
            "created_risk_points": 0,
            "created_structured_knowledge": 0,
        }

        devices_response = client.get("/devices")
        assert devices_response.status_code == 200
        devices = devices_response.json()
        assert [device["device_code"] for device in devices] == [
            "DEV-002",
            "DEV-003",
            "DEV-004",
            "DEV-005",
            "DEV-006",
            "DEV-007",
            "DEV-008",
            "DEV-009",
        ]

        dev_002_status = client.get("/devices/DEV-002/status")
        assert dev_002_status.status_code == 200
        assert dev_002_status.json()["device"]["device_type"] == "motor"
        assert dev_002_status.json()["latest_runtime_data"]["current"] == 9.6
        assert dev_002_status.json()["recent_alarms"][0]["alarm_code"] == "E404"

        dev_003_alarms = client.get("/devices/DEV-003/alarms?is_resolved=false")
        assert dev_003_alarms.status_code == 200
        assert dev_003_alarms.json()[0]["alarm_code"] == "E101"
        assert dev_003_alarms.json()[0]["message"] == "温度异常，传感器区域温度超过安全阈值。"

        dev_004_status = client.get("/devices/DEV-004/status")
        assert dev_004_status.status_code == 200
        assert dev_004_status.json()["device"]["device_type"] == "compressor"
        assert dev_004_status.json()["latest_runtime_data"]["status"] == "normal"
        assert dev_004_status.json()["recent_alarms"] == []

        dev_005_status = client.get("/devices/DEV-005/status")
        assert dev_005_status.status_code == 200
        assert dev_005_status.json()["device"]["device_type"] == "motor"
        assert dev_005_status.json()["latest_runtime_data"]["vibration"] == 0.62
        assert dev_005_status.json()["recent_alarms"][0]["alarm_code"] == "E201"

        dev_006_status = client.get("/devices/DEV-006/status")
        assert dev_006_status.status_code == 200
        assert dev_006_status.json()["device"]["device_type"] == "pump"
        assert dev_006_status.json()["recent_alarms"][0]["alarm_code"] == "E302"

        dev_007_status = client.get("/devices/DEV-007/status")
        assert dev_007_status.status_code == 200
        assert dev_007_status.json()["device"]["device_type"] == "gearbox"
        assert dev_007_status.json()["latest_runtime_data"]["temperature"] == 64.0
        assert dev_007_status.json()["recent_alarms"][0]["alarm_code"] == "E501"

        dev_008_status = client.get("/devices/DEV-008/status")
        assert dev_008_status.status_code == 200
        assert dev_008_status.json()["device"]["device_type"] == "fan"
        assert dev_008_status.json()["recent_alarms"] == []

        documents_response = client.get("/knowledge/documents")
        assert documents_response.status_code == 200
        documents = documents_response.json()
        assert {document["filename"] for document in documents} == {
            "e101_maintenance_manual.md",
            "e201_vibration_manual.md",
            "e203_controller_manual.md",
            "e302_hydraulic_pressure_manual.md",
            "e404_sensor_manual.md",
            "e501_gearbox_lubrication_manual.md",
            "enterprise_e101_temperature_abnormal_manual.md",
            "enterprise_e201_vibration_abnormal_manual.md",
            "enterprise_e203_motor_abnormal_manual.md",
            "enterprise_e404_communication_abnormal_manual.md",
            "industrial_alarm_triage_guide.md",
            "plant_preventive_maintenance_playbook.md",
        }
        assert all(document["status"] == "indexed" for document in documents)
        assert all(document["chunk_count"] == 1 for document in documents)

        history_response = client.get("/diagnosis/history")
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 6
        assert {item["alarm_code"] for item in history} >= {"E101", "E201", "E302", "E501"}

        context_response = client.get("/devices/DEV-003/context")
        assert context_response.status_code == 200
        context = context_response.json()
        assert context["health_summary"]["current_risk_level"] == "high"
        assert context["maintenance_memory"][0]["confirmed_root_cause"] == "散热滤网堵塞"
        assert context["related_knowledge"][0]["fault_code"] == "E101"
        assert context["related_knowledge"][0]["cause_count"] == 3
        assert context["related_knowledge"][0]["case_count"] == 2
        assert context["similar_cases"][0]["fault"] == "E101"

        pump_context = client.get("/devices/DEV-006/context")
        assert pump_context.status_code == 200
        assert pump_context.json()["related_knowledge"][0]["fault_code"] == "E302"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=SessionLocal.kw["bind"])


def _build_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), SessionLocal


def _load_seed_module():
    module_path = BACKEND_DIR / "scripts" / "seed_demo_data.py"
    spec = importlib.util.spec_from_file_location("seed_demo_data", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_create_document_from_file(
    db: Session,
    file_path: Path,
    original_filename: str,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        original_filename=original_filename,
        storage_filename=Path(file_path).name,
        file_type="markdown",
        file_path=str(file_path),
        file_size=Path(file_path).stat().st_size,
        status="indexed",
        chunk_count=1,
    )
    db.add(document)
    db.flush()
    db.add(
        KnowledgeChunk(
            document_id=document.id,
            chunk_index=0,
            content=Path(file_path).read_text(encoding="utf-8"),
            vector_id=f"knowledge-chunk-{document.id}",
        )
    )
    db.commit()
    db.refresh(document)
    return document


def _fake_delete_document(db: Session, document: KnowledgeDocument) -> None:
    db.delete(document)
    db.commit()
