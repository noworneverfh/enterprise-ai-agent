import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.vector_store import ChromaVectorStore, VectorStoreChunk  # noqa: E402


def test_vector_store_add_chunks_and_search(tmp_path: Path) -> None:
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="test_chunks",
    )
    chunks = [
        VectorStoreChunk(
            chunk_id="chunk-1",
            text="E101 means high temperature. Check the cooling fan.",
            embedding=[1.0, 0.0, 0.0],
            metadata={"document_id": 1, "filename": "manual.md"},
        ),
        VectorStoreChunk(
            chunk_id="chunk-2",
            text="E203 means abnormal voltage. Check power wiring.",
            embedding=[0.0, 1.0, 0.0],
            metadata={"document_id": 2, "filename": "power.md"},
        ),
        VectorStoreChunk(
            chunk_id="chunk-3",
            text="Normal device temperature should remain stable.",
            embedding=[0.8, 0.1, 0.0],
            metadata={"document_id": 3, "filename": "status.md"},
        ),
    ]

    store.add_chunks(chunks)
    results = store.search(query_embedding=[1.0, 0.0, 0.0], top_k=2)

    assert len(results) == 2
    assert results[0].chunk_id == "chunk-1"
    assert "high temperature" in results[0].content
    assert results[0].metadata["filename"] == "manual.md"
    assert isinstance(results[0].distance, float)


def test_vector_store_delete_chunks_allows_missing_ids(tmp_path: Path) -> None:
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="test_delete_chunks",
    )
    store.add_chunks(
        [
            VectorStoreChunk(
                chunk_id="vector-1",
                text="E101 temperature alarm",
                embedding=[1.0, 0.0, 0.0],
                metadata={"document_id": 1},
            ),
            VectorStoreChunk(
                chunk_id="vector-2",
                text="E203 voltage alarm",
                embedding=[0.0, 1.0, 0.0],
                metadata={"document_id": 2},
            ),
        ]
    )

    store.delete_chunks(["vector-1", "missing-vector-id"])
    results = store.search(query_embedding=[1.0, 0.0, 0.0], top_k=2)

    assert [result.chunk_id for result in results] == ["vector-2"]


def test_vector_store_delete_chunks_accepts_empty_list(tmp_path: Path) -> None:
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="test_delete_empty",
    )

    store.delete_chunks([])
