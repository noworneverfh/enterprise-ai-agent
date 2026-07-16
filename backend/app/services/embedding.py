from functools import lru_cache
from typing import Protocol


EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"


class EmbeddingModel(Protocol):
    """Minimal interface used from sentence-transformers models."""

    def encode(
        self,
        sentences: str | list[str],
        normalize_embeddings: bool = True,
    ) -> object:
        """Encode one text or many texts into vectors."""


@lru_cache(maxsize=1)
def get_embedding_model() -> EmbeddingModel:
    """Load the local embedding model lazily."""

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    """Embed one text string into a dense vector."""

    if not text.strip():
        raise ValueError("text must not be empty.")

    embedding = get_embedding_model().encode(
        text,
        normalize_embeddings=True,
    )
    return _to_float_list(embedding)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed multiple text strings into dense vectors."""

    if not texts:
        return []

    if any(not text.strip() for text in texts):
        raise ValueError("texts must not contain empty strings.")

    embeddings = get_embedding_model().encode(
        texts,
        normalize_embeddings=True,
    )
    return [_to_float_list(embedding) for embedding in embeddings]


def _to_float_list(embedding: object) -> list[float]:
    if hasattr(embedding, "tolist"):
        values = embedding.tolist()
    else:
        values = embedding

    return [float(value) for value in values]
