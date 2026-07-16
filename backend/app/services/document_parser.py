from pathlib import Path


SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


def parse_document(file_path: str | Path) -> str:
    """Parse a supported text document into plain text."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_TEXT_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {suffix}")

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as file:
        return _normalize_text(file.read())


def _normalize_text(text: str) -> str:
    """Normalize line endings while preserving document content."""

    return text.replace("\r\n", "\n").replace("\r", "\n").strip()
