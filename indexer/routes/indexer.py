from __future__ import annotations
from fastapi import APIRouter, HTTPException

from indexer.models import (
    IndexerStatus,
    IndexerProjectStats,
    IndexerProgressJob,
    IngestRequest,
    StartResponse,
    SearchRequest,
    SearchResponse,
    ClearRequest,
)
from indexer.core import indexer as core
from indexer.storage import redis as store

router = APIRouter(prefix="/indexer", tags=["indexer"])


@router.get("/status", response_model=IndexerStatus)
async def status() -> IndexerStatus:
    return await core.get_status()


@router.post("/ingest", response_model=StartResponse)
async def ingest(req: IngestRequest) -> StartResponse:
    """Index file content sent by the client. No filesystem access needed."""
    healthy = await core.get_status()
    if healthy.status != "ok":
        raise HTTPException(status_code=503, detail="Indexer backend unavailable")
    return await core.ingest_files(req)


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    healthy = await core.get_status()
    if healthy.status != "ok":
        raise HTTPException(status_code=503, detail="Indexer backend unavailable")
    return await core.search(
        project_id=req.project_id,
        query=req.query,
        top_k=req.top_k,
        min_score=req.min_score,
    )


@router.get("/projects", response_model=list[IndexerProjectStats])
async def list_projects() -> list[IndexerProjectStats]:
    """List all indexed projects with chunk and file counts."""
    rows = await store.list_projects_with_counts()
    return [IndexerProjectStats(**r) for r in rows]


@router.get("/progress", response_model=list[IndexerProgressJob])
async def get_progress() -> list[IndexerProgressJob]:
    """Return active indexing jobs with processed/total file counts."""
    healthy = await core.get_status()
    if healthy.status != "ok":
        raise HTTPException(status_code=503, detail="Indexer backend unavailable")
    rows = await store.list_active_progress()
    return [IndexerProgressJob(**r) for r in rows]


@router.delete("/clear", response_model=dict)
async def clear(req: ClearRequest) -> dict:
    healthy = await core.get_status()
    if healthy.status != "ok":
        raise HTTPException(status_code=503, detail="Indexer backend unavailable")
    n = await core.clear(req.project_id)
    return {"project_id": req.project_id, "deleted": n}
