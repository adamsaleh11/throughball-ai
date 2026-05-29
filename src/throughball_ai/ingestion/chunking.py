from dataclasses import dataclass
from hashlib import sha256


CHUNKING_VERSION = "markdown-section-v1"


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    text: str
    content_hash: str


def chunk_markdown(content: str, max_words: int = 450) -> list[DocumentChunk]:
    text = content.strip()
    if not text:
        return []
    if len(text.split()) <= max_words:
        return [
            DocumentChunk(
                chunk_index=0,
                text=text,
                content_hash=content_hash(text),
            )
        ]

    chunks: list[str] = []
    for section in _split_sections(text):
        words = section.split()
        if len(words) <= max_words:
            chunks.append(section)
            continue
        chunks.extend(_split_by_word_budget(section, max_words=max_words))

    return [
        DocumentChunk(
            chunk_index=index,
            text=chunk,
            content_hash=content_hash(chunk),
        )
        for index, chunk in enumerate(chunks)
    ]


def content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    payload = f"{CHUNKING_VERSION}\n{normalized}"
    return sha256(payload.encode("utf-8")).hexdigest()


def _split_sections(content: str) -> list[str]:
    sections: list[list[str]] = []
    current: list[str] = []

    for line in content.splitlines():
        if line.startswith("## ") and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append(current)

    return ["\n".join(section).strip() for section in sections if "\n".join(section).strip()]


def _split_by_word_budget(section: str, max_words: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in section.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for paragraph in paragraphs:
        paragraph_words = len(paragraph.split())
        if current and current_words + paragraph_words > max_words:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        if paragraph_words > max_words:
            words = paragraph.split()
            for start in range(0, len(words), max_words):
                chunks.append(" ".join(words[start : start + max_words]))
            continue
        current.append(paragraph)
        current_words += paragraph_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks
