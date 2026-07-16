import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
from app.models import KnowledgeChunk, KnowledgeDocument  # noqa: E402,F401
from app.schemas.knowledge import (  # noqa: E402
    KnowledgeChunkResponse,
    KnowledgeDocumentResponse,
)


def test_create_knowledge_document_and_chunk_models() -> None:
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
        document = KnowledgeDocument(
            original_filename="maintenance.md",
            storage_filename="storage-maintenance.md",
            file_type="markdown",
            file_path="uploads/storage-maintenance.md",
            file_size=128,
            status="indexed",
            chunk_count=1,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        chunk = KnowledgeChunk(
            document_id=document.id,
            chunk_index=0,
            content="E101 indicates abnormal temperature.",
            content_hash="hash-001",
            vector_id="chunk-001",
            start_char=0,
            end_char=36,
        )
        db.add(chunk)
        db.commit()
        db.refresh(chunk)

        document_response = KnowledgeDocumentResponse.model_validate(document)
        chunk_response = KnowledgeChunkResponse.model_validate(chunk)

        assert document_response.filename == "maintenance.md"
        response_data = document_response.model_dump()
        assert "original_filename" not in response_data
        assert "storage_filename" not in response_data
        assert "file_path" not in response_data
        assert document_response.chunk_count == 1
        assert chunk_response.document_id == document.id
        assert chunk_response.content == "E101 indicates abnormal temperature."
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
