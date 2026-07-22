from datetime import datetime
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.agent import tools as agent_tools  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import Device, DeviceAlarmRecord, DeviceRuntimeData  # noqa: E402,F401
from app.schemas.agent import (  # noqa: E402
    DeviceStatusToolInput,
    KnowledgeSearchToolInput,
)
from app.schemas.knowledge import KnowledgeSearchResult  # noqa: E402


@pytest.fixture
def db_session() -> Session:
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
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_device_tool_returns_device_runtime_and_alarm(db_session: Session) -> None:
    device = _create_device(db_session)
    db_session.add(
        DeviceRuntimeData(
            device_id=device.id,
            temperature=88.5,
            voltage=220.0,
            current=8.2,
            vibration=2.1,
            status="warning",
            recorded_at=datetime.utcnow(),
        )
    )
    db_session.add(
        DeviceAlarmRecord(
            device_id=device.id,
            alarm_code="E101",
            alarm_level="high",
            message="High temperature.",
            is_resolved=False,
            occurred_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    result = agent_tools.run_get_device_status_tool(
        db_session,
        DeviceStatusToolInput(device_code="DEV-001"),
    )

    assert result.ok is True
    assert result.device_exists is True
    assert result.device.device_code == "DEV-001"
    assert result.latest_runtime_data.temperature == 88.5
    assert result.recent_alarms[0].alarm_code == "E101"
    assert result.warnings == []


def test_device_tool_returns_not_found_as_business_result(
    db_session: Session,
) -> None:
    result = agent_tools.run_get_device_status_tool(
        db_session,
        DeviceStatusToolInput(device_code="DEV-999"),
    )

    assert result.ok is True
    assert result.device_exists is False
    assert result.device is None
    assert result.latest_runtime_data is None
    assert result.recent_alarms == []


def test_device_tool_warns_when_runtime_data_missing(db_session: Session) -> None:
    _create_device(db_session)

    result = agent_tools.run_get_device_status_tool(
        db_session,
        DeviceStatusToolInput(device_code="DEV-001"),
    )

    assert result.ok is True
    assert result.latest_runtime_data is None
    assert "No runtime data found for device." in result.warnings


def test_device_tool_warns_when_unresolved_alarms_missing(
    db_session: Session,
) -> None:
    device = _create_device(db_session)
    db_session.add(
        DeviceRuntimeData(
            device_id=device.id,
            temperature=40.0,
            voltage=220.0,
            current=4.2,
            vibration=0.3,
            status="normal",
            recorded_at=datetime.utcnow(),
        )
    )
    db_session.add(
        DeviceAlarmRecord(
            device_id=device.id,
            alarm_code="E101",
            alarm_level="high",
            message="Resolved alarm.",
            is_resolved=True,
            occurred_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    result = agent_tools.run_get_device_status_tool(
        db_session,
        DeviceStatusToolInput(device_code="DEV-001"),
    )

    assert result.ok is True
    assert result.recent_alarms == []
    assert "No unresolved alarms found for device." in result.warnings


def test_device_tool_input_trims_and_uppercases_device_code() -> None:
    input_data = DeviceStatusToolInput(device_code="  dev-001  ")

    assert input_data.device_code == "DEV-001"


def test_device_tool_rejects_alarm_limit_out_of_range() -> None:
    with pytest.raises(ValidationError):
        DeviceStatusToolInput(device_code="DEV-001", alarm_limit=21)


def test_device_tool_service_exception_returns_stable_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_get_device_by_code(db: Session, device_code: str) -> Device:
        raise RuntimeError("raw database password leaked")

    monkeypatch.setattr(
        agent_tools.device_service,
        "get_device_by_code",
        fail_get_device_by_code,
    )

    result = agent_tools.run_get_device_status_tool(
        db_session,
        DeviceStatusToolInput(device_code="DEV-001"),
    )

    assert result.ok is False
    assert result.device_exists is None
    assert result.error_code == "device_query_failed"
    assert result.warnings == ["Device status query failed."]
    assert "raw database password leaked" not in result.model_dump_json()


def test_knowledge_tool_returns_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_tools.knowledge_service,
        "search_knowledge",
        lambda query, top_k: [_knowledge_result(distance=0.31)],
    )

    result = agent_tools.run_search_knowledge_tool(
        KnowledgeSearchToolInput(query="E101 temperature", top_k=1)
    )

    assert result.ok is True
    assert result.results[0].source == "manual.md#chunk-0"
    assert result.results[0].distance == 0.31
    assert result.results[0].vector_score == 0.76
    assert result.results[0].rerank_score == 0.93
    assert result.warnings == []


def test_knowledge_tool_warns_when_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_tools.knowledge_service,
        "search_knowledge",
        lambda query, top_k: [],
    )

    result = agent_tools.run_search_knowledge_tool(
        KnowledgeSearchToolInput(query="unknown issue")
    )

    assert result.ok is True
    assert result.results == []
    assert result.warnings == ["No knowledge results found."]


def test_knowledge_tool_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        KnowledgeSearchToolInput(query="   ")


def test_knowledge_tool_rejects_top_k_out_of_range() -> None:
    with pytest.raises(ValidationError):
        KnowledgeSearchToolInput(query="temperature", top_k=0)

    with pytest.raises(ValidationError):
        KnowledgeSearchToolInput(query="temperature", top_k=6)


def test_knowledge_tool_service_exception_returns_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_search_knowledge(query: str, top_k: int) -> list[KnowledgeSearchResult]:
        raise RuntimeError("chroma internal path leaked")

    monkeypatch.setattr(
        agent_tools.knowledge_service,
        "search_knowledge",
        fail_search_knowledge,
    )

    result = agent_tools.run_search_knowledge_tool(
        KnowledgeSearchToolInput(query="temperature")
    )

    assert result.ok is False
    assert result.error_code == "knowledge_search_failed"
    assert result.results == []
    assert result.warnings == ["Knowledge search failed."]
    assert "chroma internal path leaked" not in result.model_dump_json()


def _create_device(db: Session) -> Device:
    device = Device(
        device_code="DEV-001",
        name="Demo Device",
        device_type="pump",
        location="Workshop A",
        is_online=True,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def _knowledge_result(distance: float) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=1,
        document_id=1,
        filename="manual.md",
        chunk_index=0,
        content="E101 means high temperature.",
        source="manual.md#chunk-0",
        distance=distance,
        vector_score=0.76,
        rerank_score=0.93,
    )
