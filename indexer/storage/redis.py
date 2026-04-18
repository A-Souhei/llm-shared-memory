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
    # Search for all chunks with this file_path
    try:
        q = Query(f"@file_path:{{{_escape_tag(file_path)}}}").return_fields("__key").no_content().paging(0, 10000)
        results = await r.ft(idx).search(q)
        keys = [doc.id for doc in results.docs]
    except Exception:
        keys = []
    if keys:
        await r.delete(*keys)
    # Remove from mtime cache
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
    results = await r.ft(idx).search(q, query_params={"vec": vec_bytes})
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


def _escape_tag(value: str) -> str:
    """Escape special chars for RediSearch TAG queries."""
    special = r'.,<>{}\[\]\"\':;!@#$%^&*()\-+=~'
    for ch in special:
        value = value.replace(ch, f"\\{ch}")
    return value
