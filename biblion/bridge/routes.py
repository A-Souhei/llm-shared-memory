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


@router.get("/session")
async def get_session(session_id: str = Query(...)) -> dict:
    """Resolve a session_id to its bridge_id and check master liveness.

    Returns {bridge_id, role, active} or 404 if the session is unknown.
    active=False means the master heartbeat is stale — the bridge is broken.
    """
    result = await core.get_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


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
    await core.leave(req.bridge_id, req.session_id)
    return {"success": True}


@router.post("/share-context")
async def share_context(req: ShareContextRequest) -> dict:
    # Default directory to the node's registered directory if not provided
    directory = req.directory
    if not directory:
        nodes = await core.get_nodes(req.bridge_id)
        for node in nodes:
            if node.session_id == req.session_id:
                directory = node.directory
                break

    entry = ContextEntry(
        node_id=req.session_id,
        role=req.role,
        directory=directory,
        type=req.type,
        content=req.content,
    )
    try:
        await core.share_context(req.bridge_id, req.session_id, entry)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"success": True}


@router.post("/push-task")
async def push_task(req: PushTaskRequest) -> BridgeTask:
    try:
        return await core.push_task(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/fetch-tasks")
async def fetch_tasks(
    bridge_id: str = Query(...),
    session_id: str = Query(...),
) -> list[BridgeTask]:
    return await core.fetch_tasks(bridge_id, session_id)


@router.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest) -> dict:
    await core.heartbeat(req.bridge_id, req.session_id)
    return {"success": True}
