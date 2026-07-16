import hashlib
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.models.chunk import KnowledgeChunk
from app.models.document import KnowledgeDocument
from app.services.document_parser import parse_document
from app.services.embedding import embed_documents
from app.services.text_splitter import split_text
from app.services.vector_store import ChromaVectorStore, VectorStoreChunk


def create_document_from_file(
    db: Session,
    file_path: str | Path,
    chunk_size: int = 800,
    overlap: int = 100,
    vector_store: ChromaVectorStore | None = None,
    embedding_func: Callable[[list[str]], list[list[float]]] = embed_documents,
) -> KnowledgeDocument:
    """Parse, split, embed, index, and persist one knowledge document."""

    path = Path(file_path)
    text = parse_document(path)
    text_chunks = split_text(text, chunk_size=chunk_size, overlap=overlap)

    document = KnowledgeDocument(
        filename=path.name,
        file_type=_get_file_type(path),
        file_path=str(path),
        file_size=path.stat().st_size,
        status="processing",
        chunk_count=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    if vector_store is None:
        vector_store = ChromaVectorStore()

    candidate_vector_ids: list[str] = []
    chroma_write_attempted = False

    try:
        db.add(document)

        chunk_models: list[KnowledgeChunk] = []
        for index, chunk in enumerate(text_chunks):
            chunk_model = KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk.content,
                content_hash=_hash_content(chunk.content),
                start_char=chunk.start_char,
                end_char=chunk.end_char,
            )
            db.add(chunk_model)
            chunk_models.append(chunk_model)

        db.flush()

        embeddings = embedding_func([chunk.content for chunk in chunk_models])
        if len(embeddings) != len(chunk_models):
            raise ValueError("Embedding count does not match chunk count.")

        vector_chunks: list[VectorStoreChunk] = []
        for chunk_model, embedding in zip(chunk_models, embeddings, strict=True):
            vector_id = _build_vector_id(chunk_model.id)
            chunk_model.vector_id = vector_id
            candidate_vector_ids.append(vector_id)
            vector_chunks.append(
                VectorStoreChunk(
                    chunk_id=vector_id,
                    text=chunk_model.content,
                    embedding=embedding,
                    metadata={
                        "document_id": document.id,
                        "chunk_id": chunk_model.id,
                        "filename": document.filename,
                        "chunk_index": chunk_model.chunk_index,
                        "source": f"{document.filename}#chunk-{chunk_model.chunk_index}",
                    },
                )
            )

        chroma_write_attempted = True
        vector_store.add_chunks(vector_chunks)

        document.chunk_count = len(chunk_models)
        document.status = "indexed"
        document.error_message = None
        db.commit()
        db.refresh(document)
        return document
    except Exception as exc:
        original_error = exc
        db.rollback()
        compensation_error: Exception | None = None

        if chroma_write_attempted and candidate_vector_ids:
            try:
                vector_store.delete_chunks(candidate_vector_ids)
            except Exception as delete_exc:
                compensation_error = delete_exc

        failed_document = db.get(KnowledgeDocument, document.id)
        if failed_document is None:
            raise

        failed_document.status = "failed"
        failed_document.error_message = _build_error_message(
            original_error,
            compensation_error,
        )
        failed_document.chunk_count = 0
        db.add(failed_document)
        db.commit()
        db.refresh(failed_document)
        raise


def _build_vector_id(chunk_id: int) -> str:
    return f"knowledge-chunk-{chunk_id}"


def _get_file_type(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return "txt"

    if suffix in {".md", ".markdown"}:
        return "markdown"

    return suffix.lstrip(".")


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _build_error_message(
    original_error: Exception,
    compensation_error: Exception | None,
) -> str:
    message = f"{type(original_error).__name__}: {original_error}"

    if compensation_error is not None:
        message = (
            f"{message}; compensation delete failed: "
            f"{type(compensation_error).__name__}: {compensation_error}"
        )

    return message
