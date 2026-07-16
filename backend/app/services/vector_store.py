from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings


DEFAULT_CHROMA_PATH = settings.chroma_persist_directory
DEFAULT_COLLECTION_NAME = settings.chroma_collection_name


@dataclass(frozen=True)
class VectorStoreChunk:
    """Chunk data stored in the vector database."""

    chunk_id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchResult:
    """One vector search result returned from Chroma."""

    chunk_id: str
    content: str
    metadata: dict[str, Any]
    distance: float


class ChromaVectorStore:
    """Small Chroma wrapper used by the knowledge service layer."""

    def __init__(
        self,
        persist_directory: str | Path = DEFAULT_CHROMA_PATH,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        import chromadb

        self.persist_directory = str(persist_directory)
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name
        )

    def add_chunks(self, chunks: list[VectorStoreChunk]) -> None:
        """Add text chunks, embeddings, and metadata to Chroma."""

        if not chunks:
            return

        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=[chunk.embedding for chunk in chunks],
            metadatas=[chunk.metadata for chunk in chunks],
        )

    def delete_chunks(self, vector_ids: list[str]) -> None:
        """Delete vector records by their Chroma IDs."""

        if not vector_ids:
            return

        self.collection.delete(ids=vector_ids)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        """Search Chroma and return normalized result objects."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than 0.")

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        return [
            VectorSearchResult(
                chunk_id=str(chunk_id),
                content=str(document),
                metadata=dict(metadata or {}),
                distance=float(distance),
            )
            for chunk_id, document, metadata, distance in zip(
                ids,
                documents,
                metadatas,
                distances,
                strict=True,
            )
        ]
