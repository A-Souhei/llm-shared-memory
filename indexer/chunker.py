from __future__ import annotations
import hashlib
import uuid
from dataclasses import dataclass

from indexer.config import INDEXER_CHUNK_SIZE, INDEXER_CHUNK_OVERLAP


@dataclass
class Chunk:
    chunk_id: str   # deterministic UUID derived from file_path + start_line
    file_path: str
    start_line: int  # 1-indexed
    text: str


def _make_chunk_id(file_path: str, start_line: int) -> str:
    """Deterministic UUID: MD5("{file_path}:{start_line}") as UUID."""
    raw = f"{file_path}:{start_line}"
    md5 = hashlib.md5(raw.encode()).digest()
    return str(uuid.UUID(bytes=md5))


def chunk_file(content: str, file_path: str) -> list[Chunk]:
    """Split file content into overlapping line-based chunks."""
    lines = content.splitlines()
    chunks: list[Chunk] = []
    step = INDEXER_CHUNK_SIZE - INDEXER_CHUNK_OVERLAP
    if step <= 0:
        step = 1

    i = 0
    while i < len(lines):
        end = min(i + INDEXER_CHUNK_SIZE, len(lines))
        text = "\n".join(lines[i:end])
        if text.strip():
            chunks.append(
                Chunk(
                    chunk_id=_make_chunk_id(file_path, i + 1),
                    file_path=file_path,
                    start_line=i + 1,
                    text=text,
                )
            )
        i += step

    return chunks
