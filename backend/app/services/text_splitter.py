from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    """A slice of text with original character offsets."""

    content: str
    start_char: int
    end_char: int


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
