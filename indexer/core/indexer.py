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
    import asyncio
    from biblion.embedding import embed
    from biblion.bridge import slack

    await store.redis.ensure_index(req.project_id)
    known_mtimes = await store.redis.get_all_mtimes(req.project_id)

    to_embed = [f for f in req.files
                if f.path not in known_mtimes or known_mtimes[f.path] != f.mtime]
    skipped = len(req.files) - len(to_embed)
    deleted = 0
    indexed = 0
    errors: list[str] = []

    await store.redis.set_progress(req.project_id, processed=0, total=len(to_embed))

    try:
        for i, f in enumerate(to_embed):
            await store.redis.set_progress(req.project_id, processed=i + 1, total=len(to_embed))
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

        if req.all_paths is not None:
            current = set(req.all_paths)
            for old_path in set(known_mtimes) - current:
                n = await store.redis.delete_by_path(req.project_id, old_path)
                deleted += n
    finally:
        await store.redis.clear_progress(req.project_id)

    if indexed > 0 or deleted > 0 or errors:
        asyncio.create_task(slack.indexing_done(
            project_id=req.project_id, indexed=indexed, skipped=skipped,
            deleted=deleted, errors=len(errors),
        ))

    return StartResponse(
        project_id=req.project_id,
        indexed=indexed,
        skipped=skipped,
        deleted=deleted,
        errors=errors,
    )


async def start_indexing(project_id: str, source_dir: str) -> StartResponse:
    """Walk source_dir, embed changed files, upsert chunks, delete removed files."""
    import asyncio
    from biblion.embedding import embed
    from biblion.bridge import slack

    await store.redis.ensure_index(project_id)
    known_mtimes = await store.redis.get_all_mtimes(project_id)

    root = Path(source_dir).resolve()

    # First pass: collect eligible changed files
    to_embed: list[tuple[Path, str, float]] = []
    skipped = 0
    seen_paths: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            if INDEXER_EXTENSIONS and ext not in INDEXER_EXTENSIONS:
                continue
            rel = str(fpath.relative_to(root))
            seen_paths.add(rel)
            try:
                stat = fpath.stat()
            except OSError:
                continue
            if stat.st_size > INDEXER_MAX_FILE_SIZE:
                continue
            mtime = stat.st_mtime_ns / 1_000_000
            if rel in known_mtimes and known_mtimes[rel] == mtime:
                skipped += 1
                continue
            to_embed.append((fpath, rel, mtime))

    await store.redis.set_progress(project_id, processed=0, total=len(to_embed))

    indexed = 0
    deleted = 0
    errors: list[str] = []

    try:
        for i, (fpath, rel, mtime) in enumerate(to_embed):
            await store.redis.set_progress(project_id, processed=i + 1, total=len(to_embed))
            try:
                content = fpath.read_text(errors="replace")
            except Exception as exc:
                errors.append(f"{rel}: read error: {exc}")
                continue
            chunks = chunk_file(content, rel)
            if not chunks:
                skipped += 1
                continue
            await store.redis.delete_by_path(project_id, rel)
            for chunk in chunks:
                try:
                    vector = await embed(chunk.text)
                    await store.redis.upsert(project_id, chunk, vector, mtime)
                    indexed += 1
                except Exception as exc:
                    errors.append(f"{rel}:{chunk.start_line}: embed error: {exc}")

        for old_path in set(known_mtimes.keys()) - seen_paths:
            n = await store.redis.delete_by_path(project_id, old_path)
            deleted += n
    finally:
        await store.redis.clear_progress(project_id)

    if indexed > 0 or deleted > 0 or errors:
        asyncio.create_task(slack.indexing_done(
            project_id=project_id, indexed=indexed, skipped=skipped,
            deleted=deleted, errors=len(errors),
        ))

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
