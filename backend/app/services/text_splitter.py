from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    """A slice of text with original character offsets."""

    content: str
    start_char: int
    end_char: int
    section: str | None = None
    page: int | None = None
    metadata: dict[str, str | int | None] | None = None


def split_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[TextChunk]:
    """Split long text into overlapping chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")

    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0.")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    normalized_text = text.strip()
    if not normalized_text:
        return []

    chunks: list[TextChunk] = []
    start = 0
    text_length = len(normalized_text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        content = normalized_text[start:end].strip()

        if content:
            leading_spaces = len(normalized_text[start:end]) - len(
                normalized_text[start:end].lstrip()
            )
            trailing_spaces = len(normalized_text[start:end]) - len(
                normalized_text[start:end].rstrip()
            )
            chunks.append(
                TextChunk(
                    content=content,
                    start_char=start + leading_spaces,
                    end_char=end - trailing_spaces,
                )
            )

        if end == text_length:
            break

        start = end - overlap

    return chunks


def split_document_text(
    text: str,
    *,
    file_type: str = "txt",
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[TextChunk]:
    """Split document text while preserving useful document structure."""

    if file_type == "markdown":
        markdown_chunks = _split_markdown_sections(
            text,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        if markdown_chunks:
            return markdown_chunks

    return split_text(text, chunk_size=chunk_size, overlap=overlap)


def _split_markdown_sections(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    normalized_text = text.strip()
    if not normalized_text:
        return []

    headings: list[tuple[int, str]] = []
    cursor = 0
    for line in normalized_text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                headings.append((cursor, title))
        cursor += len(line)

    if not headings:
        return []

    chunks: list[TextChunk] = []
    for index, (section_start, section_title) in enumerate(headings):
        section_end = headings[index + 1][0] if index + 1 < len(headings) else len(normalized_text)
        section_text = normalized_text[section_start:section_end].strip()
        if not section_text:
            continue

        if len(section_text) <= chunk_size:
            chunks.append(
                TextChunk(
                    content=section_text,
                    start_char=section_start,
                    end_char=section_end,
                    section=section_title,
                    metadata={"section": section_title},
                )
            )
            continue

        for chunk in split_text(section_text, chunk_size=chunk_size, overlap=overlap):
            chunks.append(
                TextChunk(
                    content=chunk.content,
                    start_char=section_start + chunk.start_char,
                    end_char=section_start + chunk.end_char,
                    section=section_title,
                    metadata={"section": section_title},
                )
            )

    return chunks
