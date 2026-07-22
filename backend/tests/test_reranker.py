from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.knowledge import KnowledgeSearchResult  # noqa: E402
from app.services import reranker  # noqa: E402


def test_reranker_orders_results_by_cross_encoder_score(monkeypatch) -> None:
    monkeypatch.setattr(reranker.settings, "reranker_enabled", True)
    monkeypatch.setattr(reranker.settings, "reranker_batch_size", 8)
    monkeypatch.setattr(reranker, "_get_reranker", lambda: FakeReranker([0.1, 0.92, 0.4]))

    results = reranker.rerank_knowledge_results(
        "E404 通信异常处理方法",
        [
            _result(1, "generic communication note", 0.11),
            _result(2, "E404 gateway timeout and wiring inspection", 0.44),
            _result(3, "PLC network maintenance", 0.2),
        ],
        top_n=2,
    )

    assert [result.chunk_id for result in results] == [2, 3]
    assert [result.rerank_score for result in results] == [0.92, 0.4]
    assert results[0].vector_score is not None


def test_reranker_returns_vector_order_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(reranker.settings, "reranker_enabled", False)

    results = reranker.rerank_knowledge_results(
        "E101 温度异常",
        [_result(1, "A", 0.1), _result(2, "B", 0.2)],
        top_n=1,
    )

    assert [result.chunk_id for result in results] == [1]
    assert results[0].rerank_score is None


def test_reranker_falls_back_to_vector_order_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(reranker.settings, "reranker_enabled", True)
    monkeypatch.setattr(reranker, "_get_reranker", lambda: BrokenReranker())

    results = reranker.rerank_knowledge_results(
        "E201 振动异常",
        [_result(1, "A", 0.1), _result(2, "B", 0.2)],
        top_n=2,
    )

    assert [result.chunk_id for result in results] == [1, 2]
    assert all(result.rerank_score is None for result in results)


def _result(chunk_id: int, content: str, distance: float) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=chunk_id,
        document_id=1,
        filename="manual.md",
        chunk_index=chunk_id - 1,
        content=content,
        source=f"manual.md#chunk-{chunk_id - 1}",
        distance=distance,
        vector_score=1 / (1 + distance),
    )


class FakeReranker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.received_batch_size: int | None = None

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int = 16,
    ) -> list[float]:
        self.received_batch_size = batch_size
        assert len(sentences) == len(self.scores)
        return self.scores


class BrokenReranker:
    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int = 16,
    ) -> list[float]:
        raise RuntimeError("reranker unavailable")
