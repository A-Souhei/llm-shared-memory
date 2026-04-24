import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from biblion import config
from biblion import embedding
from biblion.storage import redis as storage
from biblion.models import (
    WriteRequest,
    WriteResponse,
    SearchRequest,
    SearchResult,
    ListEntry,
    Status,
    StatusReady,
    StatusDisabled,
    MementoSaveRequest,
    MementoEntry,
)
from biblion.core.sanitize import sanitize
from biblion.core.canonicalize import canonicalize
from biblion.core.scoring import rank

# ---------------------------------------------------------------------------
# App-level status state
# ---------------------------------------------------------------------------

_status: dict = {"ready": False, "reason": "not initialized"}


def set_status(ready: bool, reason: str = "") -> None:
    _status["ready"] = ready
    _status["reason"] = reason


async def get_status() -> Status:
    if not _status["ready"]:
        await initialize()
    if _status["ready"]:
        try:
            entry_count = await storage.count()
        except Exception:
            entry_count = 0
        return StatusReady(
            entry_count=entry_count,
            token_count=0,
            redis_url=config.REDIS_URL,
            embedding_url=config.EMBEDDING_URL,
            embedding_model=config.EMBEDDING_MODEL,
        )
    return StatusDisabled(reason=_status["reason"])


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

async def initialize() -> None:
    emb_ok, redis_ok = await asyncio.gather(
        embedding.check_health(),
        storage.check_health(),
    )

    if not emb_ok and not redis_ok:
        set_status(False, "error")
        return
    if not emb_ok:
        set_status(False, "embedding_unreachable")
        return
    if not redis_ok:
        set_status(False, "redis_unreachable")
        return

    vector = await embedding.embed("ping")
    dim = len(vector)
    await storage.ensure_collection(dim)
    set_status(True)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def write(req: WriteRequest) -> WriteResponse:
    if not _status["ready"]:
        raise HTTPException(status_code=503, detail="biblion disabled")

    clean_content = sanitize(req.content)
    query, tags = canonicalize(clean_content, req.type, req.tags or [])
    vector = await embedding.embed(query)

    hits = await storage.search(vector, top_k=1, project_id=req.project_id or "")

    if hits and hits[0]["score"] >= config.DEDUP_THRESHOLD:
        existing_id = hits[0]["payload"].get("id", str(hits[0]["id"]))
        return WriteResponse(success=False, id=existing_id, reason="duplicate")

    now = datetime.now(timezone.utc).isoformat()
    quality_raw = req.quality if req.quality is not None else config.DEFAULT_QUALITY
    quality_float = quality_raw / 10.0

    new_id = str(uuid4())
    payload = {
        "id": new_id,
        "type": req.type,
        "content": clean_content,
        "tags": tags,
        "project_id": req.project_id,
        "branch": req.branch,
        "session_id": req.session_id,
        "quality": quality_float,
        "used_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    await storage.upsert([{"id": new_id, "vector": vector, "payload": payload}])
    return WriteResponse(success=True, id=new_id)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def search(req: SearchRequest) -> list[SearchResult]:
    if not _status["ready"]:
        raise HTTPException(status_code=503, detail="biblion disabled")

    vector = await embedding.embed(req.query)
    limit = req.limit or config.MAX_CANDIDATES

    hits = await storage.search(vector, top_k=limit, project_id=req.project_id or "")

    # Build intermediate dicts for ranking
    intermediate: list[dict] = []
    for hit in hits:
        p = hit.get("payload", {})
        intermediate.append({
            "id": p.get("id", str(hit.get("id", ""))),
            "type": p.get("type", "pattern"),
            "content": p.get("content", ""),
            "tags": p.get("tags", []),
            "quality": p.get("quality", config.DEFAULT_QUALITY),
            "used_count": p.get("used_count", 0),
            "project_id": p.get("project_id", ""),
            "similarity": hit.get("score", 0.0),
        })

    ranked = rank(intermediate)
    filtered = [e for e in ranked if e["similarity"] >= config.SEARCH_MIN_SCORE]

    results: list[SearchResult] = []
    for entry in filtered[:limit]:
        tags_raw = entry.get("tags", [])
        results.append(
            SearchResult(
                id=entry["id"],
                type=entry["type"],
                content=entry["content"],
                tags=tags_raw if isinstance(tags_raw, list) else [],
                quality=entry["quality"],
                used_count=entry["used_count"],
                similarity=entry["similarity"],
                score=entry["score"],
                project_id=entry.get("project_id", ""),
            )
        )

    return results


# ---------------------------------------------------------------------------
# List entries
# ---------------------------------------------------------------------------

async def list_entries(
    project_id: str | None = None,
    entry_type: str | None = None,
) -> list[ListEntry]:
    hits = await storage.scroll_all(project_id=project_id or "")

    entries: list[ListEntry] = []
    for hit in hits:
        p = hit.get("payload", {})
        hit_type = p.get("type", "pattern")
        if entry_type and hit_type != entry_type:
            continue
        tags_raw = p.get("tags", [])
        tags_str = ", ".join(tags_raw) if isinstance(tags_raw, list) else str(tags_raw)
        entries.append(
            ListEntry(
                id=p.get("id", str(hit.get("id", ""))),
                type=hit_type,
                tags=tags_str,
                content=p.get("content", ""),
                project_id=p.get("project_id", ""),
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Memento — save
# ---------------------------------------------------------------------------

async def save_memento(req: MementoSaveRequest) -> WriteResponse:
    if not _status["ready"]:
        raise HTTPException(status_code=503, detail="biblion disabled")
    if not req.project_id.strip():
        raise HTTPException(status_code=400, detail="project_id is required for mementos")

    now = datetime.now(timezone.utc).isoformat()
    new_id = str(uuid4())
    vector = await embedding.embed(req.content[:500])

    payload = {
        "id": new_id,
        "type": "memento",
        "content": req.content,
        "tags": [],
        "project_id": req.project_id,
        "branch": "",
        "session_id": "",
        "quality": 0.7,
        "used_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    await storage.upsert([{"id": new_id, "vector": vector, "payload": payload}])
    return WriteResponse(success=True, id=new_id)


# ---------------------------------------------------------------------------
# Memento — list (newest first)
# ---------------------------------------------------------------------------

async def list_mementos(project_id: str) -> list[MementoEntry]:
    hits = await storage.scroll_all(project_id=project_id)
    mementos = [h for h in hits if h.get("payload", {}).get("type") == "memento"]
    mementos.sort(key=lambda h: h["payload"].get("created_at", ""), reverse=True)
    return [
        MementoEntry(
            id=h["payload"]["id"],
            content=h["payload"]["content"],
            project_id=h["payload"]["project_id"],
            created_at=h["payload"].get("created_at", ""),
        )
        for h in mementos
    ]


# ---------------------------------------------------------------------------
# Delete entry
# ---------------------------------------------------------------------------

async def delete_entry(entry_id: str) -> bool:
    await storage.delete_by_id(entry_id)
    return True


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

async def clear(project_id: str | None = None) -> int:
    if project_id:
        before = await storage.count()
        await storage.delete_by_project(project_id)
        after = await storage.count()
        return max(0, before - after)
    else:
        await storage.delete_all()
        return 0
