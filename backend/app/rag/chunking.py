import hashlib
from dataclasses import dataclass, field

from app.rag.config import ChunkConfig

CHUNKER_VERSION = "v1"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_source(text: str) -> str:
    normalized = (
        text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    )
    normalized.encode("utf-8")
    return normalized


@dataclass(frozen=True)
class PreparedChunk:
    chunk_index: int
    text: str = field(repr=False)
    start_char: int
    end_char: int
    content_hash: str


def chunk_text(text: str, config: ChunkConfig) -> list[PreparedChunk]:
    source = normalize_source(text)
    chunks = []
    start = 0
    while start < len(source):
        end = min(start + config.size, len(source))
        if end < len(source):
            # Prefer paragraphs, then word boundaries in the latter half of the window.
            floor = start + max(config.size // 2, config.overlap + 1)
            paragraph = source.rfind("\n\n", floor, end)
            boundary = paragraph + 2 if paragraph >= floor else -1
            if boundary < 0:
                for index in range(end - 1, floor - 1, -1):
                    if source[index].isspace():
                        boundary = index + 1
                        break
            if boundary > start:
                end = boundary
        piece = source[start:end]
        if piece.strip():
            chunks.append(
                PreparedChunk(len(chunks), piece, start, end, text_hash(piece))
            )
        if end == len(source):
            break
        next_start = max(start + 1, end - config.overlap)
        # Move forward to a word boundary without exceeding the requested overlap.
        while (
            next_start < end and next_start > 0 and not source[next_start - 1].isspace()
        ):
            next_start += 1
        start = next_start
    return chunks
