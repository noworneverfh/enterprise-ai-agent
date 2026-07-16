from __future__ import annotations

import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services import knowledge as knowledge_service  # noqa: E402
from app.services.vector_store import VectorSearchResult  # noqa: E402


def test_search_knowledge_returns_single_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result(
                chunk_id="knowledge-chunk-1",
                content="E101 means high temperature.",
                distance=0.12,
                metadata={
                    "document_id": 1,
                    "chunk_id": 1,
                    "filename": "manual.md",
                    "chunk_index": 0,
                    "source": "manual.md#chunk-0",
                },
            )
        ],
    )

    results = knowledge_service.search_knowledge("E101 temperature", top_k=1)

    assert len(results) == 1
    assert results[0].chunk_id == 1
    assert results[0].document_id == 1
    assert results[0].filename == "manual.md"
    assert results[0].content == "E101 means high temperature."
    assert results[0].source == "manual.md#chunk-0"
    assert results[0].distance == 0.12


def test_search_knowledge_sorts_results_by_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result("vector-2", "less close", 0.45, _metadata(2, 1)),
            _vector_result("vector-1", "most close", 0.11, _metadata(1, 0)),
            _vector_result("vector-3", "least close", 0.9, _metadata(3, 2)),
        ],
    )

    results = knowledge_service.search_knowledge("temperature", top_k=3)

    assert [result.chunk_id for result in results] == [1, 2, 3]
    assert [result.distance for result in results] == [0.11, 0.45, 0.9]


def test_search_knowledge_passes_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_store = FakeVectorStore(
        [_vector_result("vector-1", "content", 0.1, _metadata(1, 0))]
    )
    monkeypatch.setattr(knowledge_service, "embed_text", lambda query: [1.0, 0.0])
    monkeypatch.setattr(knowledge_service, "ChromaVectorStore", lambda: fake_store)

    knowledge_service.search_knowledge("temperature", top_k=7)

    assert fake_store.received_top_k == 7


def test_search_knowledge_returns_empty_list_for_empty_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_search_dependencies(monkeypatch, [])

    results = knowledge_service.search_knowledge("temperature", top_k=5)

    assert results == []


def test_search_knowledge_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query must not be empty"):
        knowledge_service.search_knowledge("   ")


def test_search_knowledge_rejects_top_k_less_than_one() -> None:
    with pytest.raises(ValueError, match="top_k must be between 1 and 20"):
        knowledge_service.search_knowledge("temperature", top_k=0)


def test_search_knowledge_rejects_top_k_greater_than_twenty() -> None:
    with pytest.raises(ValueError, match="top_k must be between 1 and 20"):
        knowledge_service.search_knowledge("temperature", top_k=21)


def test_search_knowledge_rejects_missing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_search_dependencies(
        monkeypatch,
        [
            _vector_result(
                "vector-1",
                "content",
                0.1,
                {
                    "document_id": 1,
                    "filename": "manual.md",
                    "chunk_index": 0,
                    "source": "manual.md#chunk-0",
                },
            )
        ],
    )

    with pytest.raises(ValueError, match="missing required field: chunk_id"):
        knowledge_service.search_knowledge("temperature", top_k=1)


def test_search_knowledge_rejects_invalid_metadata_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata(1, 0)
    metadata["chunk_id"] = "1"
    _patch_search_dependencies(
        monkeypatch,
        [_vector_result("vector-1", "content", 0.1, metadata)],
    )

    with pytest.raises(TypeError, match="metadata field must be int: chunk_id"):
        knowledge_service.search_knowledge("temperature", top_k=1)


def _patch_search_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    results: list[VectorSearchResult],
) -> FakeVectorStore:
    fake_store = FakeVectorStore(results)
    monkeypatch.setattr(knowledge_service, "embed_text", lambda query: [1.0, 0.0])
    monkeypatch.setattr(knowledge_service, "ChromaVectorStore", lambda: fake_store)
    return fake_store


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


class FakeVectorStore:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self.results = results
        self.received_top_k: int | None = None

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        self.received_top_k = top_k
        return self.results[:top_k]
