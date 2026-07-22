import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.models import KnowledgeChunk, KnowledgeDocument  # noqa: E402,F401
from app.services.document_parser import parse_document  # noqa: E402
from app.services.knowledge import create_document_from_file  # noqa: E402
from app.services.text_splitter import split_text  # noqa: E402
from app.services.vector_store import ChromaVectorStore  # noqa: E402


def test_parse_txt_document(tmp_path: Path) -> None:
    file_path = tmp_path / "case.txt"
    file_path.write_bytes("Line 1\r\nLine 2\n".encode("utf-8"))

    text = parse_document(file_path)

    assert text == "Line 1\nLine 2"


def test_parse_markdown_document(tmp_path: Path) -> None:
    file_path = tmp_path / "maintenance.md"
    file_path.write_text("# E101\n\nCheck the cooling fan.", encoding="utf-8")

    text = parse_document(file_path)

    assert "# E101" in text
    assert "Check the cooling fan." in text


def test_parse_pdf_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "manual.pdf"
    file_path.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakePdfReader:
        def __init__(self, path: str) -> None:
            self.pages = [FakePage("E203 controller alarm."), FakePage("Check wiring.")]

    fake_pypdf = types.SimpleNamespace(PdfReader=FakePdfReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    text = parse_document(file_path)

    assert text == "E203 controller alarm.\n\nCheck wiring."


def test_split_text_with_overlap() -> None:
    chunks = split_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=3)

    assert [chunk.content for chunk in chunks] == [
        "abcdefghij",
        "hijklmnopq",
        "opqrstuvwx",
        "vwxyz",
    ]
    assert chunks[1].start_char == 7
    assert chunks[1].end_char == 17


def test_create_document_from_file_saves_chunks(tmp_path: Path) -> None:
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

    file_path = tmp_path / "manual.md"
    file_path.write_text("E101 means high temperature. Check fan.", encoding="utf-8")
    vector_store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="test_knowledge_chunks",
    )

    db = SessionLocal()
    try:
        document = create_document_from_file(
            db,
            file_path,
            chunk_size=12,
            overlap=2,
            vector_store=vector_store,
            embedding_func=_fake_embed_documents,
        )
        chunks = list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )

        assert document.filename == "manual.md"
        assert document.file_type == "markdown"
        assert document.status == "indexed"
        assert document.chunk_count == len(chunks)
        assert len(chunks) > 1
        assert chunks[0].content_hash is not None
        assert all(chunk.vector_id is not None for chunk in chunks)
        assert chunks[0].vector_id == f"knowledge-chunk-{chunks[0].id}"

        results = vector_store.search(
            query_embedding=_fake_embed_documents([chunks[0].content])[0],
            top_k=1,
        )
        assert results[0].chunk_id == chunks[0].vector_id
        assert results[0].metadata["document_id"] == document.id
        assert results[0].metadata["chunk_id"] == chunks[0].id
        assert results[0].metadata["filename"] == "manual.md"
        assert results[0].metadata["source"] == "manual.md#chunk-0"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_document_from_file_marks_failed_when_indexing_fails(
    tmp_path: Path,
) -> None:
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

    file_path = tmp_path / "manual.md"
    file_path.write_text("E101 means high temperature.", encoding="utf-8")
    vector_store = FailingVectorStore()

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="Chroma write failed"):
            create_document_from_file(
                db,
                file_path,
                chunk_size=12,
                overlap=2,
                vector_store=vector_store,
                embedding_func=_fake_embed_documents,
            )
        document = db.scalar(select(KnowledgeDocument))
        chunks = list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )

        assert document is not None
        assert document.status == "failed"
        assert "Chroma write failed" in document.error_message
        assert document.chunk_count == 0
        assert chunks == []
        assert vector_store.deleted_vector_ids == vector_store.candidate_vector_ids
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_document_from_file_deletes_vectors_when_final_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    file_path = tmp_path / "manual.md"
    file_path.write_text("E101 means high temperature.", encoding="utf-8")
    vector_store = RecordingVectorStore()

    db = SessionLocal()
    original_commit = db.commit
    commit_calls = 0

    def commit_with_final_failure() -> None:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise RuntimeError("SQLite final commit failed")
        original_commit()

    monkeypatch.setattr(db, "commit", commit_with_final_failure)

    try:
        with pytest.raises(RuntimeError, match="SQLite final commit failed"):
            create_document_from_file(
                db,
                file_path,
                chunk_size=12,
                overlap=2,
                vector_store=vector_store,
                embedding_func=_fake_embed_documents,
            )

        document = db.scalar(select(KnowledgeDocument))

        assert document is not None
        assert document.status == "failed"
        assert "SQLite final commit failed" in document.error_message
        assert vector_store.deleted_vector_ids == vector_store.candidate_vector_ids
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_document_from_file_deletes_candidate_vectors_after_partial_chroma_failure(
    tmp_path: Path,
) -> None:
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

    file_path = tmp_path / "manual.md"
    file_path.write_text("E101 means high temperature. Check fan.", encoding="utf-8")
    vector_store = PartialFailingVectorStore()

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="Partial Chroma write failed"):
            create_document_from_file(
                db,
                file_path,
                chunk_size=12,
                overlap=2,
                vector_store=vector_store,
                embedding_func=_fake_embed_documents,
            )

        document = db.scalar(select(KnowledgeDocument))

        assert document is not None
        assert document.status == "failed"
        assert vector_store.deleted_vector_ids == vector_store.candidate_vector_ids
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_create_document_from_file_does_not_delete_vectors_when_embedding_fails(
    tmp_path: Path,
) -> None:
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

    file_path = tmp_path / "manual.md"
    file_path.write_text("E101 means high temperature.", encoding="utf-8")
    vector_store = RecordingVectorStore()

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="Embedding failed"):
            create_document_from_file(
                db,
                file_path,
                chunk_size=12,
                overlap=2,
                vector_store=vector_store,
                embedding_func=_failing_embed_documents,
            )

        document = db.scalar(select(KnowledgeDocument))

        assert document is not None
        assert document.status == "failed"
        assert vector_store.deleted_vector_ids == []
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    return [[1.0, float(index), 0.0] for index, _ in enumerate(texts)]


def _failing_embed_documents(texts: list[str]) -> list[list[float]]:
    raise RuntimeError("Embedding failed")


class RecordingVectorStore:
    def __init__(self) -> None:
        self.candidate_vector_ids: list[str] = []
        self.deleted_vector_ids: list[str] = []

    def add_chunks(self, chunks) -> None:
        self.candidate_vector_ids = [chunk.chunk_id for chunk in chunks]

    def delete_chunks(self, vector_ids: list[str]) -> None:
        self.deleted_vector_ids = vector_ids


class FailingVectorStore(RecordingVectorStore):
    def add_chunks(self, chunks) -> None:
        self.candidate_vector_ids = [chunk.chunk_id for chunk in chunks]
        raise RuntimeError("Chroma write failed")


class PartialFailingVectorStore(RecordingVectorStore):
    def add_chunks(self, chunks) -> None:
        self.candidate_vector_ids = [chunk.chunk_id for chunk in chunks]
        raise RuntimeError("Partial Chroma write failed")
