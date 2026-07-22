from pathlib import Path


SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_DOCUMENT_EXTENSIONS = {*SUPPORTED_TEXT_EXTENSIONS, ".pdf"}


def parse_document(file_path: str | Path) -> str:
    """Parse a supported text document into plain text."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {suffix}")

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if suffix == ".pdf":
        return _parse_pdf(path)

    with path.open("r", encoding="utf-8", newline="") as file:
        return _normalize_text(file.read())


def _normalize_text(text: str) -> str:
    """Normalize line endings while preserving document content."""

    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _parse_pdf(path: Path) -> str:
    """Extract text from a PDF document."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires pypdf to be installed.") from exc

    reader = PdfReader(str(path))
    pages = [
        page_text.strip()
        for page in reader.pages
        if (page_text := page.extract_text())
    ]
    text = _normalize_text("\n\n".join(pages))
    if not text:
        raise ValueError("PDF document does not contain extractable text.")

    return text
