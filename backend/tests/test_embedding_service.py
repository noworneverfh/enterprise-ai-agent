import sys
from types import ModuleType
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services import embedding as embedding_service  # noqa: E402


class FakeEmbeddingModel:
    def encode(
        self,
        sentences: str | list[str],
        normalize_embeddings: bool = True,
    ) -> list[float] | list[list[float]]:
        assert normalize_embeddings is True

        if isinstance(sentences, str):
            return [1.0, 0.5, 0.25]

        return [[float(index), float(index + 1)] for index, _ in enumerate(sentences)]


def test_embed_text(monkeypatch) -> None:
    monkeypatch.setattr(
        embedding_service,
        "get_embedding_model",
        lambda: FakeEmbeddingModel(),
    )

    embedding = embedding_service.embed_text("设备温度过高")

    assert embedding == [1.0, 0.5, 0.25]


def test_embed_documents(monkeypatch) -> None:
    monkeypatch.setattr(
        embedding_service,
        "get_embedding_model",
        lambda: FakeEmbeddingModel(),
    )

    embeddings = embedding_service.embed_documents(["E101 报警", "检查风扇"])

    assert embeddings == [[0.0, 1.0], [1.0, 2.0]]


def test_get_embedding_model_uses_existing_env_model_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loaded_models: list[str] = []
    local_model_path = tmp_path / "bge-small-zh-v1.5"
    local_model_path.mkdir()

    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str) -> None:
            loaded_models.append(model_name_or_path)

    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setenv(
        embedding_service.EMBEDDING_MODEL_PATH_ENV,
        str(local_model_path),
    )
    embedding_service.get_embedding_model.cache_clear()

    try:
        embedding_service.get_embedding_model()
    finally:
        embedding_service.get_embedding_model.cache_clear()

    assert loaded_models == [str(local_model_path)]


def test_get_embedding_model_falls_back_to_default_model_name(monkeypatch) -> None:
    loaded_models: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str) -> None:
            loaded_models.append(model_name_or_path)

    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.delenv(embedding_service.EMBEDDING_MODEL_PATH_ENV, raising=False)
    embedding_service.get_embedding_model.cache_clear()

    try:
        embedding_service.get_embedding_model()
    finally:
        embedding_service.get_embedding_model.cache_clear()

    assert loaded_models == [embedding_service.EMBEDDING_MODEL_NAME]


def test_get_embedding_model_rejects_missing_env_model_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loaded_models: list[str] = []
    missing_model_path = tmp_path / "missing-bge-small-zh-v1.5"

    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str) -> None:
            loaded_models.append(model_name_or_path)

    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setenv(
        embedding_service.EMBEDDING_MODEL_PATH_ENV,
        str(missing_model_path),
    )
    embedding_service.get_embedding_model.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="local embedding model directory"):
            embedding_service.get_embedding_model()
    finally:
        embedding_service.get_embedding_model.cache_clear()

    assert loaded_models == []
