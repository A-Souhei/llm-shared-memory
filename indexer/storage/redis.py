from __future__ import annotations
import struct
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.commands.search.field import TagField, TextField, NumericField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from indexer.config import (
    REDIS_URL,
    REDIS_KEY_PREFIX,
    EMBEDDING_DIM,
    INDEXER_TOP_K,
    INDEXER_MIN_SCORE,
)
from indexer.chunker import Chunk

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=False)
    return _client


def _index_name(project_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}_{project_id}"


def _point_key(project_id: str, chunk_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}_{project_id}:point:{chunk_id}"


def _mtime_key(project_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}_{project_id}:mtimes"


def _progress_key(project_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}_{project_id}:progress"


async def check_health() -> bool:
    try:
        r = _get_client()
        return await r.ping()
    except Exception:
        return False


async def ensure_index(project_id: str) -> None:
    """Create RediSearch index for project if it does not exist."""
    r = _get_client()
    idx = _index_name(project_id)
    prefix = f"{REDIS_KEY_PREFIX}_{project_id}:point:"
    try:
        await r.ft(idx).info()
        return  # already exists
    except Exception:
        pass  # index doesn't exist, create it

    schema = (
        TagField("file_path"),
        TextField("text"),
        NumericField("start_line"),
        NumericField("mtime"),
        VectorField(
            "vector",
            "HNSW",
            {
                "TYPE": "FLOAT32",
                "DIM": EMBEDDING_DIM,
                "DISTANCE_METRIC": "COSINE",
            },
        ),
    )
    definition = IndexDefinition(prefix=[prefix], index_type=IndexType.HASH)
    await r.ft(idx).create_index(schema, definition=definition)
    logger.info("Created RediSearch index: %s", idx)


async def upsert(project_id: str, chunk: Chunk, vector: list[float], mtime: float) -> None:
    r = _get_client()
    key = _point_key(project_id, chunk.chunk_id)
    vec_bytes = struct.pack(f"{len(vector)}f", *vector)
    mapping: dict[bytes | str, Any] = {
        "file_path": chunk.file_path,
        "text": chunk.text,
        "start_line": chunk.start_line,
        "mtime": mtime,
        "vector": vec_bytes,
    }
    await r.hset(key, mapping=mapping)
    # Update mtime cache
    mtime_key = _mtime_key(project_id)
    await r.zadd(mtime_key, {chunk.file_path: mtime})


async def delete_by_path(project_id: str, file_path: str) -> int:
    """Delete all chunks for a given file path. Returns number of deleted keys."""
    r = _get_client()
    idx = _index_name(project_id)
    try:
        q = Query(f"@file_path:{{{_escape_tag(file_path)}}}").no_content().paging(0, 10000)
        results = await r.ft(idx).search(q)
        keys = [doc.id for doc in results.docs]
    except Exception:
        logger.warning("delete_by_path query failed for %s/%s, falling back to scan", project_id, file_path)
        keys = []
    if not keys:
        # Fallback: scan all point keys and match by file_path field
        prefix = f"{REDIS_KEY_PREFIX}_{project_id}:point:"
        cursor = 0
        while True:
            cursor, batch = await r.scan(cursor, match=f"{prefix}*", count=500)
            for k in batch:
                val = await r.hget(k, "file_path")
                if val and (val.decode() if isinstance(val, bytes) else val) == file_path:
                    keys.append(k)
            if cursor == 0:
                break
    if keys:
        await r.delete(*keys)
    await r.zrem(_mtime_key(project_id), file_path)
    return len(keys)


async def get_all_mtimes(project_id: str) -> dict[str, float]:
    """Return {file_path: mtime} from the sorted set cache."""
    r = _get_client()
    raw = await r.zrange(_mtime_key(project_id), 0, -1, withscores=True)
    return {
        (k.decode() if isinstance(k, bytes) else k): score
        for k, score in raw
    }


async def search(
    project_id: str,
    query_vector: list[float],
    top_k: int = INDEXER_TOP_K,
    min_score: float = INDEXER_MIN_SCORE,
) -> list[dict]:
    r = _get_client()
    idx = _index_name(project_id)
    vec_bytes = struct.pack(f"{len(query_vector)}f", *query_vector)
    q = (
        Query(f"*=>[KNN {top_k} @vector $vec AS score]")
        .sort_by("score")
        .return_fields("file_path", "text", "start_line", "score")
        .paging(0, top_k)
        .dialect(2)
    )
    try:
        results = await r.ft(idx).search(q, query_params={"vec": vec_bytes})
    except Exception:
        return []
    out = []
    for doc in results.docs:
        raw_score = float(getattr(doc, "score", 1.0))
        # COSINE distance → similarity
        similarity = 1.0 - raw_score
        if similarity < min_score:
            continue
        out.append({
            "file_path": doc.file_path if isinstance(doc.file_path, str) else doc.file_path.decode(),
            "start_line": int(doc.start_line),
            "text": doc.text if isinstance(doc.text, str) else doc.text.decode(),
            "score": round(similarity, 4),
        })
    return out


async def delete_all(project_id: str) -> int:
    """Delete all data for a project. Returns number of deleted keys."""
    r = _get_client()
    prefix = f"{REDIS_KEY_PREFIX}_{project_id}:"
    cursor = 0
    keys = []
    while True:
        cursor, batch = await r.scan(cursor, match=f"{prefix}*", count=500)
        keys.extend(batch)
        if cursor == 0:
            break
    if keys:
        await r.delete(*keys)
    # Drop the search index
    try:
        await r.ft(_index_name(project_id)).dropindex(delete_documents=False)
    except Exception:
        pass
    return len(keys)


async def set_progress(project_id: str, processed: int, total: int) -> None:
    r = _get_client()
    key = _progress_key(project_id)
    pipe = r.pipeline()
    pipe.hset(key, mapping={"processed": processed, "total": total})
    pipe.expire(key, 3600)
    await pipe.execute()


async def clear_progress(project_id: str) -> None:
    r = _get_client()
    await r.delete(_progress_key(project_id))


async def list_active_progress() -> list[dict]:
    r = _get_client()
    cursor = 0
    keys: list = []
    pattern = f"{REDIS_KEY_PREFIX}_*:progress"
    while True:
        cursor, batch = await r.scan(cursor, match=pattern, count=100)
        keys.extend(batch)
        if cursor == 0:
            break

    if not keys:
        return []

    pipe = r.pipeline()
    for key in keys:
        pipe.hgetall(key)
    all_data = await pipe.execute()

    result = []
    for key, data in zip(keys, all_data):
        if not data:
            continue
        k = key.decode() if isinstance(key, bytes) else key
        project_id = k[len(REDIS_KEY_PREFIX) + 1:].rsplit(":progress", 1)[0]
        decoded = {
            (dk.decode() if isinstance(dk, bytes) else dk):
            (dv.decode() if isinstance(dv, bytes) else dv)
            for dk, dv in data.items()
        }
        try:
            processed = int(decoded.get("processed", 0))
        except (TypeError, ValueError):
            processed = 0
        try:
            total = int(decoded.get("total", 0))
        except (TypeError, ValueError):
            total = 0
        result.append({"project_id": project_id, "processed": processed, "total": total})
    return result


async def list_projects() -> list[str]:
    """Return list of known project IDs by scanning for mtime keys."""
    r = _get_client()
    cursor = 0
    projects = []
    pattern = f"{REDIS_KEY_PREFIX}_*:mtimes"
    while True:
        cursor, batch = await r.scan(cursor, match=pattern, count=500)
        for key in batch:
            k = key.decode() if isinstance(key, bytes) else key
            # extract project_id from "{prefix}_{project_id}:mtimes"
            inner = k[len(REDIS_KEY_PREFIX) + 1:]  # strip "indexer_"
            project_id = inner.rsplit(":mtimes", 1)[0]
            projects.append(project_id)
        if cursor == 0:
            break
    return projects


async def list_projects_with_counts() -> list[dict]:
    """Return [{project_id, chunk_count, file_count}] for all indexed projects."""
    r = _get_client()
    projects = list(dict.fromkeys(await list_projects()))  # deduplicate, preserve order
    result = []
    for project_id in projects:
        file_count = int(await r.zcard(_mtime_key(project_id)))
        try:
            info = await r.ft(_index_name(project_id)).info()
            raw = info.get("num_docs") if info.get("num_docs") is not None else info.get(b"num_docs", 0)
            try:
                chunk_count = int(raw)
            except (TypeError, ValueError):
                chunk_count = 0
        except Exception:
            logger.warning("Failed to get FT.INFO for project %s", project_id, exc_info=True)
            chunk_count = 0
        result.append({"project_id": project_id, "chunk_count": chunk_count, "file_count": file_count})
    return result


def _escape_tag(value: str) -> str:
    """Escape special chars for RediSearch TAG queries."""
    special = r'.,<>{}\[\]\"\':;!@#$%^&*()\-+=~/ '
    for ch in special:
        value = value.replace(ch, f"\\{ch}")
    return value
