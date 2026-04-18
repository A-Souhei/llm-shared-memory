"""Redis Stack vector storage backend for biblion."""
from __future__ import annotations
import json
import struct
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.commands.search.field import TagField, TextField, NumericField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from biblion import config

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(config.REDIS_URL, decode_responses=False)
    return _client


def _point_key(point_id: str) -> str:
    return f"{config.COLLECTION_NAME}:point:{point_id}"


def _index_name() -> str:
    return config.COLLECTION_NAME


async def check_health() -> bool:
    try:
        r = _get_client()
        return await r.ping()
    except Exception:
        return False


async def ensure_collection(dim: int) -> None:
    """Create RediSearch index if it does not exist."""
    r = _get_client()
    idx = _index_name()
    prefix = f"{config.COLLECTION_NAME}:point:"
    try:
        await r.ft(idx).info()
        return  # already exists
    except Exception:
        pass

    schema = (
        TextField("id"),
        TagField("type"),
        TextField("content"),
        TagField("tags", separator=","),
        TagField("project_id"),
        TagField("branch"),
        TagField("session_id"),
        NumericField("quality"),
        NumericField("used_count"),
        TextField("created_at"),
        TextField("updated_at"),
        VectorField(
            "vector",
            "HNSW",
            {
                "TYPE": "FLOAT32",
                "DIM": dim,
                "DISTANCE_METRIC": "COSINE",
            },
        ),
    )
    definition = IndexDefinition(prefix=[prefix], index_type=IndexType.HASH)
    await r.ft(idx).create_index(schema, definition=definition)
    logger.info("Created RediSearch index: %s", idx)


async def upsert(points: list[dict]) -> None:
    """Insert or update points. Each point has: id, vector, payload."""
    r = _get_client()
    for point in points:
        point_id = str(point["id"])
        vector = point["vector"]
        payload = point.get("payload", {})

        vec_bytes = struct.pack(f"{len(vector)}f", *vector)

        # Flatten tags list to comma-separated string for TAG field
        tags = payload.get("tags", [])
        if isinstance(tags, list):
            tags_str = ",".join(str(t) for t in tags)
        else:
            tags_str = str(tags)

        mapping: dict[str, Any] = {
            "id": point_id,
            "type": payload.get("type", ""),
            "content": payload.get("content", ""),
            "tags": tags_str,
            "project_id": payload.get("project_id", "") or "",
            "branch": payload.get("branch", "") or "",
            "session_id": payload.get("session_id", "") or "",
            "quality": float(payload.get("quality", 0.5)),
            "used_count": int(payload.get("used_count", 0)),
            "created_at": payload.get("created_at", ""),
            "updated_at": payload.get("updated_at", ""),
            "vector": vec_bytes,
        }
        await r.hset(_point_key(point_id), mapping=mapping)


def _doc_to_hit(doc: Any) -> dict:
    """Convert a RediSearch document to the payload dict format biblion expects."""
    def _str(v: Any) -> str:
        return v.decode() if isinstance(v, bytes) else (v or "")

    tags_raw = _str(getattr(doc, "tags", ""))
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    payload = {
        "id": _str(getattr(doc, "id_field", "") or getattr(doc, "id", "")),
        "type": _str(getattr(doc, "type", "")),
        "content": _str(getattr(doc, "content", "")),
        "tags": tags,
        "project_id": _str(getattr(doc, "project_id", "")),
        "branch": _str(getattr(doc, "branch", "")),
        "session_id": _str(getattr(doc, "session_id", "")),
        "quality": float(getattr(doc, "quality", 0.5) or 0.5),
        "used_count": int(float(getattr(doc, "used_count", 0) or 0)),
        "created_at": _str(getattr(doc, "created_at", "")),
        "updated_at": _str(getattr(doc, "updated_at", "")),
    }
    # The "id" stored in the hash field — fall back to doc.id (the Redis key)
    if not payload["id"]:
        key = _str(doc.id)
        # strip the point key prefix to get the UUID
        prefix = f"{config.COLLECTION_NAME}:point:"
        if key.startswith(prefix):
            payload["id"] = key[len(prefix):]
        else:
            payload["id"] = key
    return payload


async def search(
    vector: list[float],
    top_k: int,
    project_id: str = "",
) -> list[dict]:
    """Return top_k hits with payload and score."""
    r = _get_client()
    vec_bytes = struct.pack(f"{len(vector)}f", *vector)

    if project_id:
        filter_str = f"@project_id:{{{_escape_tag(project_id)}}}"
        query_str = f"({filter_str})=>[KNN {top_k} @vector $vec AS score]"
    else:
        query_str = f"*=>[KNN {top_k} @vector $vec AS score]"

    fields = ["id", "type", "content", "tags", "project_id", "branch",
              "session_id", "quality", "used_count", "created_at", "updated_at", "score"]

    q = (
        Query(query_str)
        .sort_by("score")
        .return_fields(*fields)
        .paging(0, top_k)
        .dialect(2)
    )
    try:
        results = await r.ft(_index_name()).search(q, query_params={"vec": vec_bytes})
    except Exception as exc:
        logger.warning("Redis search failed: %s", exc)
        return []

    hits = []
    for doc in results.docs:
        raw_score = float(getattr(doc, "score", 1.0))
        similarity = 1.0 - raw_score  # cosine distance → similarity
        payload = _doc_to_hit(doc)
        hits.append({"id": payload["id"], "payload": payload, "score": similarity})
    return hits


async def scroll_all(project_id: str = "") -> list[dict]:
    """Return all points (no vector) with optional project_id filter."""
    r = _get_client()

    if project_id:
        query_str = f"@project_id:{{{_escape_tag(project_id)}}}"
    else:
        query_str = "*"

    fields = ["id", "type", "content", "tags", "project_id", "branch",
              "session_id", "quality", "used_count", "created_at", "updated_at"]

    page_size = 100
    offset = 0
    results_all = []

    while True:
        q = (
            Query(query_str)
            .return_fields(*fields)
            .paging(offset, page_size)
            .dialect(2)
        )
        try:
            results = await r.ft(_index_name()).search(q)
        except Exception as exc:
            logger.warning("Redis scroll failed: %s", exc)
            break
        docs = results.docs
        for doc in docs:
            payload = _doc_to_hit(doc)
            results_all.append({"id": payload["id"], "payload": payload})
        if len(docs) < page_size:
            break
        offset += page_size

    return results_all


async def delete_by_id(point_id: str) -> None:
    r = _get_client()
    await r.delete(_point_key(point_id))


async def delete_by_project(project_id: str) -> None:
    """Delete all points belonging to a project."""
    r = _get_client()
    q = (
        Query(f"@project_id:{{{_escape_tag(project_id)}}}")
        .return_fields("id")
        .no_content()
        .paging(0, 10000)
        .dialect(2)
    )
    try:
        results = await r.ft(_index_name()).search(q)
        keys = [doc.id for doc in results.docs]
        if keys:
            await r.delete(*keys)
    except Exception as exc:
        logger.warning("delete_by_project failed: %s", exc)


async def delete_all() -> None:
    """Delete all biblion points and drop the index."""
    r = _get_client()
    prefix = f"{config.COLLECTION_NAME}:point:"
    cursor = 0
    keys = []
    while True:
        cursor, batch = await r.scan(cursor, match=f"{prefix}*", count=500)
        keys.extend(batch)
        if cursor == 0:
            break
    if keys:
        await r.delete(*keys)
    try:
        await r.ft(_index_name()).dropindex(delete_documents=False)
    except Exception:
        pass


async def update_payload(point_id: str, payload: dict) -> None:
    """Partially update hash fields for a point."""
    r = _get_client()
    key = _point_key(point_id)
    # Filter out vector key if accidentally passed
    update = {k: v for k, v in payload.items() if k != "vector" and v is not None}
    if update:
        await r.hset(key, mapping=update)


async def count() -> int:
    """Return total number of points."""
    r = _get_client()
    try:
        info = await r.ft(_index_name()).info()
        return int(info.get("num_docs", 0))
    except Exception:
        return 0


def _escape_tag(value: str) -> str:
    special = r'.,<>{}\[\]\"\':;!@#$%^&*()\-+=~/ '
    for ch in special:
        value = value.replace(ch, f"\\{ch}")
    return value
