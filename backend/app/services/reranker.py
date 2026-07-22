from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol, Sequence

from app.core.config import settings
from app.schemas.knowledge import KnowledgeSearchResult


logger = logging.getLogger(__name__)


class _CrossEncoderLike(Protocol):
    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int = 16,
    ) -> Sequence[float]:
        """Return one relevance score per query/document pair."""


def rerank_knowledge_results(
    query: str,
    results: list[KnowledgeSearchResult],
    *,
    top_n: int,
) -> list[KnowledgeSearchResult]:
    """Reorder vector candidates with a cross-encoder reranker when enabled."""

    if not settings.reranker_enabled or not results:
        return results[:top_n]

    try:
        model = _get_reranker()
        pairs = [(query, result.content) for result in results]
        scores = model.predict(pairs, batch_size=settings.reranker_batch_size)
        scored_results = [
            result.model_copy(update={"rerank_score": float(score)})
            for result, score in zip(results, scores, strict=True)
        ]
    except Exception as exc:
        logger.exception(
            "Knowledge reranker failed; falling back to vector retrieval order. "
            "exception_type=%s error=%s",
            type(exc).__name__,
            exc,
        )
        return results[:top_n]

    return sorted(
        scored_results,
        key=lambda result: (
            -(result.rerank_score if result.rerank_score is not None else float("-inf")),
            result.distance,
        ),
    )[:top_n]


@lru_cache
def _get_reranker() -> _CrossEncoderLike:
    """Load the configured reranker lazily so tests and disabled mode stay light."""

    from sentence_transformers import CrossEncoder

    model_name_or_path = settings.reranker_model_path or settings.reranker_model_name
    return CrossEncoder(model_name_or_path)
