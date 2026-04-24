from fastapi import APIRouter, HTTPException, Query

from biblion.models import WriteRequest, SearchRequest, WriteResponse, SearchResult, ListEntry, Status, MementoSaveRequest, MementoEntry
from biblion.core import biblion as core

router = APIRouter(prefix="/biblion")


@router.get("/status")
async def get_status() -> Status:
    """Get the current status of the biblion service."""
    return await core.get_status()


@router.get("/list")
async def list_entries(
    project_id: str | None = Query(None),
    type: str | None = Query(None)
) -> list[ListEntry]:
    """List all biblion entries with optional filtering."""
    return await core.list_entries(project_id, type)


@router.post("/search")
async def search(req: SearchRequest) -> list[SearchResult]:
    """Search biblion entries."""
    return await core.search(req)


@router.post("/write")
async def write(req: WriteRequest) -> WriteResponse:
    """Write a new biblion entry."""
    return await core.write(req)


@router.delete("/clear")
async def clear(project_id: str | None = Query(None)) -> dict[str, int]:
    """Clear all biblion entries with optional project filtering."""
    deleted = await core.clear(project_id)
    return {"deleted": deleted}


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str) -> dict[str, bool]:
    """Delete a specific biblion entry by ID."""
    await core.delete_entry(entry_id)
    return {"deleted": True}


@router.post("/memento/save")
async def save_memento(req: MementoSaveRequest) -> WriteResponse:
    """Save a session memento (project-scoped, no deduplication)."""
    return await core.save_memento(req)


@router.get("/memento/list")
async def list_mementos(project_id: str = Query(...)) -> list[MementoEntry]:
    """List mementos for a project, newest first."""
    return await core.list_mementos(project_id)
