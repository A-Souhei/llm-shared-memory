from __future__ import annotations
from fastapi import APIRouter, HTTPException

from indexer.models import (
    IndexerStatus,
    IngestRequest,
    StartResponse,
    SearchRequest,
    SearchResponse,
    ClearRequest,
)
from indexer.core import indexer as core

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


@router.delete("/clear", response_model=dict)
async def clear(req: ClearRequest) -> dict:
    healthy = await core.get_status()
    if healthy.status != "ok":
        raise HTTPException(status_code=503, detail="Indexer backend unavailable")
    n = await core.clear(req.project_id)
    return {"project_id": req.project_id, "deleted": n}
