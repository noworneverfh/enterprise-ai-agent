from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402
    FaultCause,
    FaultKnowledgeEntry,
    InspectionStep,
    KnowledgeChunk,
    KnowledgeDocument,
    MaintenanceAction,
    MaintenanceCase,
)
from app.services import knowledge as knowledge_service  # noqa: E402
from app.services.knowledge import create_document_from_file  # noqa: E402
from app.services.vector_store import VectorSearchResult  # noqa: E402


def test_structured_fault_knowledge_models_can_be_saved() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        document = KnowledgeDocument(
            original_filename="e201_vibration_manual.md",
            storage_filename="e201_vibration_manual.md",
            file_type="markdown",
            file_path=None,
            file_size=100,
            title="E201 振动异常维护手册",
            version="v1",
            source="enterprise-demo",
            device_type="motor",
            model="Vibration Motor E",
            status="indexed",
            chunk_count=1,
        )
        db.add(document)
        db.flush()

        entry = FaultKnowledgeEntry(
            document_id=document.id,
            fault_code="E201",
            fault_name="振动异常",
            description="设备振动值超过允许范围。",
            severity="high",
            device_type="motor",
            model="Vibration Motor E",
            trigger_conditions={"vibration": ">0.4mm/s"},
        )
        db.add(entry)
        db.flush()
        db.add_all(
            [
                FaultCause(
                    fault_entry_id=entry.id,
                    cause="轴承磨损",
                    priority=1,
                    evidence="振动升高并伴随异响",
                    verification_method="检查轴承温度和润滑状态",
                ),
                InspectionStep(
                    fault_entry_id=entry.id,
                    order=1,
                    operation="检查地脚螺栓和联轴器",
                    expected_result="无松动或偏心",
                    safety_requirement="停机挂牌后检查",
                ),
                MaintenanceAction(
                    fault_entry_id=entry.id,
                    priority=1,
                    action="降低负载并复测振动",
                    condition="振动超过阈值",
                ),
                MaintenanceCase(
                    fault_entry_id=entry.id,
                    device="DEV-005",
                    fault="E201",
                    symptom="振动值 0.62mm/s",
                    root_cause="联轴器松动",
                    solution="紧固联轴器",
                    result="振动恢复正常",
                ),
            ]
        )
        db.commit()

        saved = db.scalar(select(FaultKnowledgeEntry).where(FaultKnowledgeEntry.fault_code == "E201"))
        assert saved is not None
        assert saved.document.title == "E201 振动异常维护手册"
        assert saved.causes[0].cause == "轴承磨损"
        assert saved.inspection_steps[0].operation == "检查地脚螺栓和联轴器"
        assert saved.maintenance_actions[0].action == "降低负载并复测振动"
        assert saved.cases[0].device == "DEV-005"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_document_indexing_preserves_markdown_sections_and_metadata(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    file_path = tmp_path / "e101_temperature_abnormal_manual.md"
    file_path.write_text(
        "\n".join(
            [
                "# E101 温度异常维护手册",
                "version: v1",
                "source: enterprise-demo",
                "device_type: sensor",
                "model: Temperature Sensor C",
                "",
                "## 故障说明",
                "E101 表示温度超过安全范围。",
                "",
                "## 排查步骤",
                "检查散热风扇、滤网和温度传感器。",
            ]
        ),
        encoding="utf-8",
    )
    vector_store = RecordingVectorStore()

    db = SessionLocal()
    try:
        document = create_document_from_file(
            db,
            file_path,
            chunk_size=120,
            overlap=10,
            vector_store=vector_store,
            embedding_func=lambda texts: [[1.0, float(index)] for index, _ in enumerate(texts)],
        )

        chunks = list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )

        assert document.title == "E101 温度异常维护手册"
        assert document.version == "v1"
        assert document.source == "enterprise-demo"
        assert document.device_type == "sensor"
        assert document.model == "Temperature Sensor C"
        assert {chunk.section for chunk in chunks} >= {"E101 温度异常维护手册", "故障说明", "排查步骤"}
        assert all(chunk.chunk_metadata for chunk in chunks)
        assert vector_store.chunks
        assert vector_store.chunks[0].metadata["fault_code"] == "E101"
        assert vector_store.chunks[0].metadata["device_type"] == "sensor"
        assert vector_store.chunks[0].metadata["title"] == "E101 温度异常维护手册"
        assert "summary" in vector_store.chunks[0].metadata
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_search_knowledge_exact_fault_code_rejects_wrong_reference(monkeypatch) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result(
                "vector-e404",
                "E404 通信异常维护手册，检查网络连接。",
                0.08,
                {
                    **_metadata(404, 0),
                    "filename": "e404_communication_abnormal_manual.md",
                    "source": "e404_communication_abnormal_manual.md#chunk-0",
                    "fault_code": "E404",
                    "title": "E404 通信异常维护手册",
                },
            ),
            _vector_result(
                "vector-e101",
                "E101 温度异常维护手册，检查散热和传感器。",
                0.58,
                {
                    **_metadata(101, 0),
                    "filename": "e101_temperature_abnormal_manual.md",
                    "source": "e101_temperature_abnormal_manual.md#chunk-0",
                    "fault_code": "E101",
                    "title": "E101 温度异常维护手册",
                    "section": "排查步骤",
                    "summary": "检查散热风扇、滤网和温度传感器。",
                },
            ),
        ],
    )

    results = knowledge_service.search_knowledge("E101 温度异常原因", top_k=5)

    assert [result.source for result in results] == [
        "e101_temperature_abnormal_manual.md#chunk-0"
    ]
    assert results[0].citation is not None
    assert results[0].citation.document == "E101 温度异常维护手册"
    assert results[0].citation.section == "排查步骤"


def test_search_knowledge_device_type_metadata_reranks(monkeypatch) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result(
                "vector-sensor",
                "E201 vibration word appears but this is a sensor reference.",
                0.25,
                {
                    **_metadata(1, 0),
                    "filename": "sensor_general_manual.md",
                    "source": "sensor_general_manual.md#chunk-0",
                    "device_type": "sensor",
                },
            ),
            _vector_result(
                "vector-motor",
                "电机 motor 振动 异常 轴承 检查 E201。",
                0.29,
                {
                    **_metadata(2, 0),
                    "filename": "e201_vibration_abnormal_manual.md",
                    "source": "e201_vibration_abnormal_manual.md#chunk-0",
                    "device_type": "motor",
                    "fault_code": "E201",
                    "title": "E201 振动异常维护手册",
                },
            ),
        ],
    )

    results = knowledge_service.search_knowledge("电机 振动 异常 轴承", top_k=2)

    assert results[0].source == "e201_vibration_abnormal_manual.md#chunk-0"


def test_search_knowledge_returns_empty_when_no_reliable_evidence(monkeypatch) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result(
                "vector-unrelated",
                "E404 通信异常，与液压系统无关。",
                0.95,
                {
                    **_metadata(1, 0),
                    "filename": "e404_communication_abnormal_manual.md",
                    "source": "e404_communication_abnormal_manual.md#chunk-0",
                    "fault_code": "E404",
                },
            )
        ],
    )

    assert knowledge_service.search_knowledge("液压异常维修方法", top_k=5) == []


class RecordingVectorStore:
    def __init__(self) -> None:
        self.chunks = []

    def add_chunks(self, chunks) -> None:
        self.chunks = list(chunks)

    def delete_chunks(self, vector_ids: list[str]) -> None:
        pass


class FakeVectorStore:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self.results = results

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorSearchResult]:
        return self.results[:top_k]


def _patch_search_dependencies(monkeypatch, results: list[VectorSearchResult]) -> None:
    monkeypatch.setattr(knowledge_service, "embed_text", lambda query: [1.0, 0.0])
    monkeypatch.setattr(knowledge_service, "ChromaVectorStore", lambda: FakeVectorStore(results))


def _vector_result(
    chunk_id: str,
    content: str,
    distance: float,
    metadata: dict[str, object],
) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        content=content,
        metadata=metadata,
        distance=distance,
    )


def _metadata(chunk_id: int, chunk_index: int) -> dict[str, object]:
    return {
        "document_id": 1,
        "chunk_id": chunk_id,
        "filename": "manual.md",
        "chunk_index": chunk_index,
        "source": f"manual.md#chunk-{chunk_index}",
    }
