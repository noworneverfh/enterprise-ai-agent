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

from app.api import knowledge as knowledge_api  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KnowledgeChunk, KnowledgeDocument  # noqa: E402,F401
from app.services import knowledge as knowledge_service  # noqa: E402
from app.services.vector_store import ChromaVectorStore  # noqa: E402


@pytest.fixture
def knowledge_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
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

    upload_directory = tmp_path / "uploads"
    chroma_directory = tmp_path / "chroma"

    monkeypatch.setattr(settings, "upload_directory", str(upload_directory))
    monkeypatch.setattr(settings, "max_upload_size", 5 * 1024 * 1024)
    monkeypatch.setattr(
        knowledge_api.settings,
        "upload_directory",
        str(upload_directory),
    )
    monkeypatch.setattr(knowledge_api.settings, "max_upload_size", 5 * 1024 * 1024)
    monkeypatch.setattr(knowledge_service, "embed_documents", _fake_embed_documents)
    monkeypatch.setattr(knowledge_service, "embed_text", _fake_embed_text)
    monkeypatch.setattr(
        knowledge_service,
        "ChromaVectorStore",
        lambda: ChromaVectorStore(
            persist_directory=chroma_directory,
            collection_name="test_knowledge_api",
        ),
    )

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


def test_upload_txt_document_success(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="e101_maintenance_manual.txt",
        content=b"E101 high temperature. Check fan.",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "e101_maintenance_manual.txt"
    assert "original_filename" not in data
    assert "storage_filename" not in data
    assert "file_path" not in data
    assert data["file_type"] == "txt"


def test_upload_markdown_document_success(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.md",
        content=b"# E101\nCheck fan.",
    )

    assert response.status_code == 201
    assert response.json()["file_type"] == "markdown"


def test_uploaded_document_is_indexed(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.md",
        content=b"E101 high temperature. Check fan.",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "indexed"


def test_uploaded_document_has_chunks(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.md",
        content=b"E101 high temperature. Check fan.",
    )

    assert response.status_code == 201
    assert response.json()["chunk_count"] > 0


def test_upload_unsupported_extension_returns_415(
    knowledge_client: TestClient,
) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.pdf",
        content=b"content",
    )

    assert response.status_code == 415


def test_upload_empty_file_returns_400(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.txt",
        content=b"",
    )

    assert response.status_code == 400


def test_upload_two_mb_file_succeeds(
    knowledge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        knowledge_api.knowledge_service,
        "create_document_from_file",
        _fake_create_document_from_file,
    )

    response = _upload_file(
        knowledge_client,
        filename="large.txt",
        content=b"x" * (2 * 1024 * 1024),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "indexed"


def test_upload_six_mb_file_returns_413(knowledge_client: TestClient) -> None:
    response = _upload_file(
        knowledge_client,
        filename="manual.txt",
        content=b"x" * (6 * 1024 * 1024),
    )

    assert response.status_code == 413


def test_upload_file_is_deleted_when_indexing_fails(
    knowledge_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_indexing(db: Session, file_path: str | Path) -> KnowledgeDocument:
        raise RuntimeError("indexing failed")

    monkeypatch.setattr(
        knowledge_api.knowledge_service,
        "create_document_from_file",
        fail_indexing,
    )

    response = _upload_file(
        knowledge_client,
        filename="manual.txt",
        content=b"E101 high temperature.",
    )
    uploaded_files = [
        path for path in Path(settings.upload_directory).iterdir() if path.is_file()
    ]

    assert response.status_code == 500
    assert uploaded_files == []


def test_list_documents(knowledge_client: TestClient) -> None:
    first = _upload_file(knowledge_client, "first.txt", b"first content")
    second = _upload_file(knowledge_client, "second.txt", b"second content")

    response = knowledge_client.get("/knowledge/documents")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["id"] == second.json()["id"]
    assert response.json()[1]["id"] == first.json()["id"]


def test_get_document(knowledge_client: TestClient) -> None:
    upload_response = _upload_file(
        knowledge_client,
        filename="manual.txt",
        content=b"E101 high temperature.",
    )
    document_id = upload_response.json()["id"]

    response = knowledge_client.get(f"/knowledge/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["id"] == document_id


def test_get_missing_document_returns_404(knowledge_client: TestClient) -> None:
    response = knowledge_client.get("/knowledge/documents/999")

    assert response.status_code == 404


def test_list_chunks_ordered_by_chunk_index(knowledge_client: TestClient) -> None:
    upload_response = _upload_file(
        knowledge_client,
        filename="manual.txt",
        content=b"abcdefghijklmnopqrstuvwxyz",
    )
    document_id = upload_response.json()["id"]

    response = knowledge_client.get(f"/knowledge/documents/{document_id}/chunks")

    assert response.status_code == 200
    chunk_indexes = [chunk["chunk_index"] for chunk in response.json()]
    assert chunk_indexes == sorted(chunk_indexes)


def test_search_returns_source_and_distance(knowledge_client: TestClient) -> None:
    _upload_file(
        knowledge_client,
        filename="e101_maintenance_manual.md",
        content=b"E101 high temperature. Check fan.",
    )

    response = knowledge_client.post(
        "/knowledge/search",
        json={"query": "temperature", "top_k": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "temperature"
    assert len(data["results"]) == 1
    assert data["results"][0]["filename"] == "e101_maintenance_manual.md"
    assert data["results"][0]["source"] == "e101_maintenance_manual.md#chunk-0"
    assert isinstance(data["results"][0]["distance"], float)


def test_search_invalid_params_return_400(knowledge_client: TestClient) -> None:
    response = knowledge_client.post(
        "/knowledge/search",
        json={"query": "   ", "top_k": 1},
    )

    assert response.status_code == 400


def _upload_file(
    client: TestClient,
    filename: str,
    content: bytes,
) -> object:
    return client.post(
        "/knowledge/documents",
        files={"file": (filename, content, "text/plain")},
    )


def _fake_embed_text(text: str) -> list[float]:
    return [1.0, 0.0, 0.0]


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    return [[1.0, float(index), 0.0] for index, _ in enumerate(texts)]


def _fake_create_document_from_file(
    db: Session,
    file_path: str | Path,
    original_filename: str | None = None,
) -> KnowledgeDocument:
    path = Path(file_path)
    document = KnowledgeDocument(
        original_filename=original_filename or path.name,
        storage_filename=path.name,
        file_type=path.suffix.lstrip("."),
        file_path=str(path),
        file_size=path.stat().st_size,
        status="indexed",
        chunk_count=1,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
