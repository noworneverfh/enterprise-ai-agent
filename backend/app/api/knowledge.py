from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.chunk import KnowledgeChunk
from app.models.document import KnowledgeDocument
from app.schemas.knowledge import (
    KnowledgeChunkResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services import knowledge as knowledge_service


SUPPORTED_DOCUMENT_EXTENSIONS = {".txt", ".md", ".markdown"}

router = APIRouter(
    prefix="/knowledge",
    tags=["Knowledge"],
)


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    saved_path: Path | None = None

    try:
        original_filename, suffix = _validate_filename(file.filename)
        content = await _read_and_validate_file(file)
        saved_path = _save_upload_file(content, suffix)
        return knowledge_service.create_document_from_file(
            db,
            saved_path,
            original_filename=original_filename,
        )
    except HTTPException:
        _delete_saved_file(saved_path)
        raise
    except Exception as exc:
        cleanup_error = _delete_saved_file(saved_path)
        detail = f"Document indexing failed: {exc}"
        if cleanup_error is not None:
            detail = f"{detail}; upload cleanup failed: {cleanup_error}"

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc
    finally:
        await file.close()


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
)
def search_knowledge(
    search_request_data: dict[str, Any] = Body(...),
) -> KnowledgeSearchResponse:
    try:
        search_request = KnowledgeSearchRequest.model_validate(search_request_data)
        results = knowledge_service.search_knowledge(
            query=search_request.query,
            top_k=search_request.top_k,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return KnowledgeSearchResponse(
        query=search_request.query,
        results=results,
    )


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def list_documents(
    db: Session = Depends(get_db),
) -> list[KnowledgeDocument]:
    return knowledge_service.list_documents(db)


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    return _get_document_or_404(db, document_id)


@router.get(
    "/documents/{document_id}/chunks",
    response_model=list[KnowledgeChunkResponse],
)
def list_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
) -> list[KnowledgeChunk]:
    document = _get_document_or_404(db, document_id)
    return knowledge_service.list_document_chunks(db, document)


def _validate_filename(filename: str | None) -> tuple[str, str]:
    if filename is None or not filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    clean_name = filename.strip()
    if Path(clean_name).name != clean_name or "/" in clean_name or "\\" in clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    suffix = Path(clean_name).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type.",
        )

    return clean_name, suffix


async def _read_and_validate_file(file: UploadFile) -> bytes:
    content = await file.read(settings.max_upload_size + 1)

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File is too large.",
        )

    if not content or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must not be empty.",
        )

    return content


def _save_upload_file(content: bytes, suffix: str) -> Path:
    upload_directory = Path(settings.upload_directory)
    upload_directory.mkdir(parents=True, exist_ok=True)
    resolved_upload_directory = upload_directory.resolve()
    file_path = (resolved_upload_directory / f"{uuid4().hex}{suffix}").resolve()

    if resolved_upload_directory not in file_path.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path.",
        )

    if file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload filename collision.",
        )

    try:
        file_path.write_bytes(content)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    return file_path


def _delete_saved_file(file_path: Path | None) -> Exception | None:
    if file_path is None:
        return None

    try:
        file_path.unlink(missing_ok=True)
    except Exception as exc:
        return exc

    return None


def _get_document_or_404(db: Session, document_id: int) -> KnowledgeDocument:
    document = knowledge_service.get_document(db, document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )

    return document
