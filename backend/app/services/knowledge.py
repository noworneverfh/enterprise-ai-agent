import hashlib
from pathlib import Path
import re
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import KnowledgeChunk
from app.models.document import KnowledgeDocument
from app.schemas.knowledge import KnowledgeCitation, KnowledgeSearchResult
from app.services.document_parser import parse_document
from app.services.embedding import embed_documents, embed_text
from app.services.reranker import rerank_knowledge_results
from app.services.text_splitter import split_document_text
from app.services.vector_store import (
    ChromaVectorStore,
    VectorSearchResult,
    VectorStoreChunk,
)


def create_document_from_file(
    db: Session,
    file_path: str | Path,
    original_filename: str | None = None,
    chunk_size: int = 800,
    overlap: int = 100,
    vector_store: ChromaVectorStore | None = None,
    embedding_func: Callable[[list[str]], list[list[float]]] | None = None,
) -> KnowledgeDocument:
    """Parse, split, embed, index, and persist one knowledge document."""

    path = Path(file_path)
    display_filename = original_filename or path.name
    text = parse_document(path)
    file_type = _get_file_type(path)
    document_metadata = _extract_document_metadata(text, display_filename, file_type)
    text_chunks = split_document_text(
        text,
        file_type=file_type,
        chunk_size=chunk_size,
        overlap=overlap,
    )

    document = KnowledgeDocument(
        original_filename=display_filename,
        storage_filename=path.name,
        file_type=file_type,
        file_path=str(path.resolve()),
        file_size=path.stat().st_size,
        title=document_metadata.get("title"),
        version=document_metadata.get("version"),
        source=document_metadata.get("source"),
        device_type=document_metadata.get("device_type"),
        model=document_metadata.get("model"),
        status="processing",
        chunk_count=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    if vector_store is None:
        vector_store = ChromaVectorStore()

    if embedding_func is None:
        embedding_func = embed_documents

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
                section=chunk.section,
                page=chunk.page,
                chunk_metadata={
                    **(chunk.metadata or {}),
                    **_extract_chunk_metadata(chunk.content),
                },
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
                    metadata=_clean_chroma_metadata(
                        {
                        "document_id": document.id,
                        "chunk_id": chunk_model.id,
                        "filename": document.original_filename,
                        "chunk_index": chunk_model.chunk_index,
                        "source": (
                            f"{document.original_filename}"
                            f"#chunk-{chunk_model.chunk_index}"
                        ),
                        "title": document.title,
                        "document_source": document.source,
                        "device_type": document.device_type,
                        "model": document.model,
                        "section": chunk_model.section,
                        "page": chunk_model.page,
                        "fault_code": _first_fault_code(chunk_model.content),
                        "summary": _summarize_chunk(chunk_model.content),
                        **(chunk_model.chunk_metadata or {}),
                        }
                    ),
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


def list_documents(db: Session) -> list[KnowledgeDocument]:
    """Return knowledge documents ordered by newest first."""

    return list(
        db.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
        ).all()
    )


def get_document(db: Session, document_id: int) -> KnowledgeDocument | None:
    """Return one knowledge document by ID."""

    return db.get(KnowledgeDocument, document_id)


def list_document_chunks(
    db: Session,
    document: KnowledgeDocument,
) -> list[KnowledgeChunk]:
    """Return chunks for one document ordered by chunk index."""

    return list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
    )


def delete_document(
    db: Session,
    document: KnowledgeDocument,
    vector_store: ChromaVectorStore | None = None,
) -> None:
    """Delete a knowledge document, its chunks, vector records, and local file."""

    chunks = list_document_chunks(db, document)
    vector_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]

    if vector_store is None:
        vector_store = ChromaVectorStore()

    vector_store.delete_chunks(vector_ids)

    file_path = Path(document.file_path) if document.file_path else None
    db.delete(document)
    db.commit()

    if file_path is not None:
        file_path.unlink(missing_ok=True)


def search_knowledge(
    query: str,
    top_k: int = 5,
) -> list[KnowledgeSearchResult]:
    """Search indexed knowledge chunks. Smaller distance means closer meaning."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty.")

    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20.")

    query_embedding = embed_text(normalized_query)
    vector_store = ChromaVectorStore()
    candidate_k = top_k
    if settings.reranker_enabled:
        candidate_k = min(
            20,
            max(top_k, settings.reranker_candidate_k),
        )
    vector_results = vector_store.search(
        query_embedding=query_embedding,
        top_k=candidate_k,
    )
    search_results = [
        _to_knowledge_search_result(result) for result in vector_results
    ]
    search_results = _rerank_results(normalized_query, search_results)
    search_results = rerank_knowledge_results(
        normalized_query,
        search_results,
        top_n=candidate_k,
    )
    exact_alarm_results = _filter_exact_alarm_code_results(
        normalized_query,
        search_results,
    )
    if exact_alarm_results:
        return _sort_exact_alarm_results(exact_alarm_results)[:top_k]

    filtered_results = [
        result
        for result in search_results
        if result.distance <= settings.knowledge_search_max_distance
    ]

    return filtered_results[:top_k]


def search_knowledge_with_context(
    query: str,
    *,
    top_k: int = 5,
    device_type: str | None = None,
    fault_codes: list[str] | None = None,
    historical_terms: list[str] | None = None,
) -> list[KnowledgeSearchResult]:
    """Context-aware retrieval wrapper that keeps the legacy search API stable."""

    query_parts = [query, device_type, *(fault_codes or []), *(historical_terms or [])]
    contextual_query = " ".join(
        part.strip()
        for part in query_parts
        if isinstance(part, str) and part.strip()
    )
    results = search_knowledge(contextual_query or query, top_k=top_k)
    if not fault_codes and not device_type:
        return results
    return _context_filter_and_rerank(results, device_type=device_type, fault_codes=fault_codes or [])[:top_k]


def _context_filter_and_rerank(
    results: list[KnowledgeSearchResult],
    *,
    device_type: str | None,
    fault_codes: list[str],
) -> list[KnowledgeSearchResult]:
    normalized_codes = {code.upper() for code in fault_codes}
    normalized_device_type = device_type.lower() if device_type else None

    def score(result: KnowledgeSearchResult) -> tuple[int, float]:
        metadata_score = 0
        if normalized_codes and result.fault_code and result.fault_code.upper() in normalized_codes:
            metadata_score -= 3
        if (
            normalized_device_type
            and result.device_type
            and result.device_type.lower() == normalized_device_type
        ):
            metadata_score -= 1
        return (metadata_score, result.distance)

    return sorted(results, key=score)


def _filter_exact_alarm_code_results(
    query: str,
    results: list[KnowledgeSearchResult],
) -> list[KnowledgeSearchResult]:
    alarm_codes = {
        match.group(0).upper()
        for match in re.finditer(r"(?<![A-Za-z0-9])E\d{3,}(?![A-Za-z0-9])", query)
    }
    if not alarm_codes:
        return []

    return [
        result
        for result in results
        if any(_result_contains_alarm_code(result, alarm_code) for alarm_code in alarm_codes)
    ]


def _result_contains_alarm_code(
    result: KnowledgeSearchResult,
    alarm_code: str,
) -> bool:
    haystack = " ".join(
        [
            result.filename,
            result.source,
            result.content,
            result.fault_code or "",
            result.device_type or "",
            result.section or "",
        ]
    ).upper()
    return alarm_code in haystack


def _build_vector_id(chunk_id: int) -> str:
    return f"knowledge-chunk-{chunk_id}"


def _to_knowledge_search_result(
    vector_result: VectorSearchResult,
) -> KnowledgeSearchResult:
    metadata = vector_result.metadata

    return KnowledgeSearchResult(
        chunk_id=_require_metadata_int(metadata, "chunk_id"),
        document_id=_require_metadata_int(metadata, "document_id"),
        filename=_require_metadata_str(metadata, "filename"),
        chunk_index=_require_metadata_int(metadata, "chunk_index"),
        content=vector_result.content,
        source=_require_metadata_str(metadata, "source"),
        distance=vector_result.distance,
        vector_score=_distance_to_similarity(vector_result.distance),
        rerank_score=None,
        citation=KnowledgeCitation(
            document=_optional_metadata_str(metadata, "title")
            or _require_metadata_str(metadata, "filename"),
            section=_optional_metadata_str(metadata, "section"),
            summary=_optional_metadata_str(metadata, "summary"),
        ),
        fault_code=_optional_metadata_str(metadata, "fault_code"),
        device_type=_optional_metadata_str(metadata, "device_type"),
        section=_optional_metadata_str(metadata, "section"),
    )


def _sort_exact_alarm_results(
    results: list[KnowledgeSearchResult],
) -> list[KnowledgeSearchResult]:
    if settings.reranker_enabled:
        return sorted(
            results,
            key=lambda result: (
                -(result.rerank_score if result.rerank_score is not None else -1.0),
                result.distance,
            ),
        )

    return sorted(results, key=lambda result: result.distance)


def _distance_to_similarity(distance: float) -> float:
    return 1.0 / (1.0 + max(0.0, distance))


def _require_metadata_int(metadata: dict[str, object], key: str) -> int:
    if key not in metadata:
        raise ValueError(f"Chroma metadata missing required field: {key}")

    value = metadata[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Chroma metadata field must be int: {key}")

    return value


def _require_metadata_str(metadata: dict[str, object], key: str) -> str:
    if key not in metadata:
        raise ValueError(f"Chroma metadata missing required field: {key}")

    value = metadata[key]
    if not isinstance(value, str):
        raise TypeError(f"Chroma metadata field must be str: {key}")

    return value


def _optional_metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _rerank_results(
    query: str,
    results: list[KnowledgeSearchResult],
) -> list[KnowledgeSearchResult]:
    query_alarm_codes = _extract_fault_codes(query)
    query_device_types = _extract_device_types(query)
    query_keywords = _query_keywords(query)

    def score(result: KnowledgeSearchResult) -> tuple[float, float]:
        metadata_score = 0.0
        haystack = " ".join(
            [
                result.filename,
                result.source,
                result.content,
                result.citation.document if result.citation else "",
                result.citation.section if result.citation and result.citation.section else "",
                result.fault_code or "",
                result.device_type or "",
                result.section or "",
            ]
        ).upper()

        if query_alarm_codes and any(code in haystack for code in query_alarm_codes):
            metadata_score += 0.55

        normalized_text = haystack.lower()
        if query_device_types and any(device_type in normalized_text for device_type in query_device_types):
            metadata_score += 0.18

        keyword_hits = sum(1 for keyword in query_keywords if keyword.lower() in normalized_text)
        if keyword_hits:
            metadata_score += min(0.22, keyword_hits * 0.04)

        adjusted_distance = max(0.0, result.distance - metadata_score)
        return (adjusted_distance, result.distance)

    return sorted(results, key=score)


def _extract_document_metadata(
    text: str,
    filename: str,
    file_type: str,
) -> dict[str, str | None]:
    title = _first_heading(text) or Path(filename).stem
    fault_code = _first_fault_code(text)
    return {
        "title": title,
        "version": _metadata_line(text, "version") or "v1",
        "source": _metadata_line(text, "source") or filename,
        "device_type": _metadata_line(text, "device_type")
        or _infer_device_type(f"{filename}\n{text}"),
        "model": _metadata_line(text, "model"),
        "fault_code": fault_code,
        "file_type": file_type,
    }


def _extract_chunk_metadata(content: str) -> dict[str, str | int | None]:
    return {
        "fault_code": _first_fault_code(content),
        "device_type": _infer_device_type(content),
        "summary": _summarize_chunk(content),
    }


def _clean_chroma_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if value is not None and not isinstance(value, (dict, list))
    }


def _first_fault_code(text: str) -> str | None:
    codes = _extract_fault_codes(text)
    return codes[0] if codes else None


def _extract_fault_codes(text: str) -> list[str]:
    result: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])E\d{3,}(?![A-Za-z0-9])", text, re.IGNORECASE):
        code = match.group(0).upper()
        if code not in result:
            result.append(code)
    return result


def _extract_device_types(query: str) -> set[str]:
    mapping = {
        "motor": ("motor", "电机", "马达"),
        "sensor": ("sensor", "传感器", "温度"),
        "controller": ("controller", "控制器", "控制"),
        "communication": ("communication", "通信", "通讯", "网络"),
        "compressor": ("compressor", "压缩机"),
    }
    lowered = query.lower()
    return {
        device_type
        for device_type, keywords in mapping.items()
        if any(keyword.lower() in lowered for keyword in keywords)
    }


def _infer_device_type(text: str) -> str | None:
    device_types = _extract_device_types(text)
    if not device_types:
        return None
    return sorted(device_types)[0]


def _query_keywords(query: str) -> set[str]:
    keywords = {
        "温度",
        "振动",
        "电流",
        "电压",
        "通信",
        "报警",
        "故障",
        "维修",
        "处理",
        "原因",
        "过热",
        "轴承",
        "控制器",
        "传感器",
    }
    return {keyword for keyword in keywords if keyword in query}


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def _metadata_line(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*[:：]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _summarize_chunk(content: str, max_length: int = 160) -> str:
    text = " ".join(
        line.strip().lstrip("#").strip()
        for line in content.splitlines()
        if line.strip()
    )
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


def _get_file_type(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return "txt"

    if suffix in {".md", ".markdown"}:
        return "markdown"

    if suffix == ".pdf":
        return "pdf"

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
