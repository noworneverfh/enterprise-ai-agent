from pathlib import Path

from modelscope.hub.snapshot_download import snapshot_download


MODEL_ID = "AI-ModelScope/bge-small-zh-v1.5"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = PROJECT_ROOT / "models" / "bge-small-zh-v1.5"


def main() -> None:
    """Download the embedding model from ModelScope for local Docker usage."""

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL_ID,
        local_dir=str(TARGET_DIR),
    )
    print(f"Embedding model downloaded to: {TARGET_DIR}")


if __name__ == "__main__":
    main()
