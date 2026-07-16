import sys
from pathlib import Path


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
