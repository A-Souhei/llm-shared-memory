"""Bridge mode REST routes."""
from fastapi import APIRouter, HTTPException, Query

from biblion.bridge import core
from biblion.bridge.models import (
    BridgeInfo, BridgeTask, ContextEntry, NodeInfo,
    SetMasterRequest, SetFriendRequest,
    LeaveRequest, ShareContextRequest,
    PushTaskRequest, HeartbeatRequest,
)

router = APIRouter(prefix="/bridge")


@router.get("/list")
async def list_bridges() -> list[BridgeInfo]:
    return await core.list_bridges()


@router.get("/info")
async def get_info(bridge_id: str = Query(...)) -> BridgeInfo | None:
    return await core.get_info(bridge_id)


@router.get("/nodes")
async def get_nodes(bridge_id: str = Query(...)) -> list[NodeInfo]:
    return await core.get_nodes(bridge_id)


@router.get("/context")
async def get_context(
    bridge_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ContextEntry]:
    return await core.get_context(bridge_id, limit)


@router.post("/set-master")
async def set_master(req: SetMasterRequest) -> BridgeInfo:
    try:
        return await core.set_master(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/set-friend")
async def set_friend(req: SetFriendRequest) -> BridgeInfo:
    try:
        return await core.set_friend(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leave")
async def leave(req: LeaveRequest) -> dict:
    await core.leave(req.bridgeID, req.sessionID)
    return {"success": True}


@router.post("/share-context")
async def share_context(req: ShareContextRequest) -> dict:
    entry = ContextEntry(
        nodeID=req.sessionID,
        role=req.role,
        directory=req.directory,
        type=req.type,
        content=req.content,
    )
    await core.share_context(req.bridgeID, req.sessionID, entry)
    return {"success": True}


@router.post("/push-task")
async def push_task(req: PushTaskRequest) -> BridgeTask:
    try:
        return await core.push_task(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/fetch-tasks")
async def fetch_tasks(
    bridge_id: str = Query(...),
    session_id: str = Query(...),
) -> list[BridgeTask]:
    return await core.fetch_tasks(bridge_id, session_id)


@router.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest) -> dict:
    await core.heartbeat(req.bridgeID, req.sessionID)
    return {"success": True}
