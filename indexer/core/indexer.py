from __future__ import annotations
import logging
import os
from pathlib import Path

from indexer.config import (
    INDEXER_EXTENSIONS,
    INDEXER_MAX_FILE_SIZE,
    INDEXER_TOP_K,
    INDEXER_MIN_SCORE,
    REDIS_URL,
)
from indexer.chunker import chunk_file
from indexer.models import IndexerStatus, StartResponse, SearchResult, SearchResponse, IngestRequest
from indexer import storage as store

logger = logging.getLogger(__name__)

_healthy: bool = False


async def initialize() -> None:
    global _healthy
    _healthy = await store.redis.check_health()
    if _healthy:
        logger.info("Indexer: Redis connection OK (%s)", REDIS_URL)
    else:
        logger.warning("Indexer: Redis unavailable — indexer disabled")


async def get_status() -> IndexerStatus:
    healthy = await store.redis.check_health()
    if not healthy:
        return IndexerStatus(status="disabled", reason="redis_unreachable", redis_url=REDIS_URL)
    projects = await store.redis.list_projects()
    return IndexerStatus(status="ok", redis_url=REDIS_URL, projects=projects)


async def ingest_files(req: IngestRequest) -> StartResponse:
    """Index files whose content is provided by the caller (no filesystem access)."""
    from biblion.embedding import embed

    await store.redis.ensure_index(req.project_id)
    known_mtimes = await store.redis.get_all_mtimes(req.project_id)

    indexed = skipped = deleted = 0
    errors: list[str] = []

    for f in req.files:
        if f.path in known_mtimes and known_mtimes[f.path] == f.mtime:
            skipped += 1
            continue

        await store.redis.delete_by_path(req.project_id, f.path)

        chunks = chunk_file(f.content, f.path)
        if not chunks:
            skipped += 1
            continue

        for chunk in chunks:
            try:
                vector = await embed(chunk.text)
                await store.redis.upsert(req.project_id, chunk, vector, f.mtime)
                indexed += 1
            except Exception as exc:
                errors.append(f"{f.path}:{chunk.start_line}: {exc}")

    # Delete chunks for files that no longer exist (requires all_paths from client)
    if req.all_paths:
        current = set(req.all_paths)
        for old_path in set(known_mtimes) - current:
            n = await store.redis.delete_by_path(req.project_id, old_path)
            deleted += n

    return StartResponse(
        project_id=req.project_id,
        indexed=indexed,
        skipped=skipped,
        deleted=deleted,
        errors=errors,
    )


async def start_indexing(project_id: str, source_dir: str) -> StartResponse:
    """Walk source_dir, embed changed files, upsert chunks, delete removed files."""
    from biblion.embedding import embed  # reuse biblion's embed function

    await store.redis.ensure_index(project_id)
    known_mtimes = await store.redis.get_all_mtimes(project_id)

    indexed = 0
    skipped = 0
    deleted = 0
    errors: list[str] = []
    seen_paths: set[str] = set()

    root = Path(source_dir).resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            if INDEXER_EXTENSIONS and ext not in INDEXER_EXTENSIONS:
                skipped += 1
                continue

            rel = str(fpath.relative_to(root))
            seen_paths.add(rel)

            try:
                stat = fpath.stat()
            except OSError:
                skipped += 1
                continue

            if stat.st_size > INDEXER_MAX_FILE_SIZE:
                skipped += 1
                continue

            mtime = stat.st_mtime_ns / 1_000_000  # ms

            # Skip if mtime unchanged
            if rel in known_mtimes and known_mtimes[rel] == mtime:
                skipped += 1
                continue

            try:
                content = fpath.read_text(errors="replace")
            except Exception as exc:
                errors.append(f"{rel}: read error: {exc}")
                continue

            chunks = chunk_file(content, rel)
            if not chunks:
                skipped += 1
                continue

            # Delete stale chunks for this file first
            await store.redis.delete_by_path(project_id, rel)

            for chunk in chunks:
                try:
                    vector = await embed(chunk.text)
                    await store.redis.upsert(project_id, chunk, vector, mtime)
                    indexed += 1
                except Exception as exc:
                    errors.append(f"{rel}:{chunk.start_line}: embed error: {exc}")

    # Delete chunks for files that no longer exist
    for old_path in set(known_mtimes.keys()) - seen_paths:
        n = await store.redis.delete_by_path(project_id, old_path)
        deleted += n

    return StartResponse(
        project_id=project_id,
        indexed=indexed,
        skipped=skipped,
        deleted=deleted,
        errors=errors,
    )


async def search(
    project_id: str,
    query: str,
    top_k: int = INDEXER_TOP_K,
    min_score: float = INDEXER_MIN_SCORE,
) -> SearchResponse:
    from biblion.embedding import embed

    vector = await embed(query)
    raw = await store.redis.search(project_id, vector, top_k=top_k, min_score=min_score)
    results = [
        SearchResult(
            file_path=r["file_path"],
            start_line=r["start_line"],
            text=r["text"],
            score=r["score"],
        )
        for r in raw
    ]
    return SearchResponse(results=results)


async def clear(project_id: str) -> int:
    return await store.redis.delete_all(project_id)
