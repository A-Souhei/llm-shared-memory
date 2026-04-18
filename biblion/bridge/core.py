"""Bridge mode core logic — Redis-backed master/friend coordination."""
from __future__ import annotations
import json
import logging
import time

import redis.asyncio as aioredis

from biblion import config
from biblion.bridge import slack
from biblion.bridge.models import (
    BridgeInfo, BridgeTask, ContextEntry, NodeInfo,
    PushTaskRequest, SetMasterRequest, SetFriendRequest,
)

logger = logging.getLogger(__name__)

STALE_MS = 60_000  # 60 seconds
CONTEXT_MAX = 200

_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    return _client


def _keys(bridge_id: str) -> dict[str, str]:
    return {
        "master": f"bridge:{bridge_id}:master",
        "nodes": f"bridge:{bridge_id}:nodes",
        "context": f"bridge:{bridge_id}:context",
        "channel": f"bridge:{bridge_id}:channel",
        "limit": f"bridge:{bridge_id}:limit",
    }


def _session_key(session_id: str) -> str:
    return f"bridge:sessions:{session_id}"


def _slug_key(slug: str) -> str:
    return f"bridge:slug:{slug}"


async def set_master(req: SetMasterRequest) -> BridgeInfo:
    r = _get_client()
    bridge_id = req.sessionID
    k = _keys(bridge_id)
    now_ms = time.time() * 1000

    await r.hset(k["master"], mapping={
        "sessionID": req.sessionID,
        "slug": req.slug,
        "title": req.title,
        "directory": req.directory,
        "nodeURL": req.nodeURL,
        "heartbeat": now_ms,
        "project_id": req.project_id,
    })

    node = NodeInfo(
        nodeID=req.sessionID,
        role="master",
        sessionID=req.sessionID,
        slug=req.slug,
        title=req.title,
        directory=req.directory,
        nodeURL=req.nodeURL,
        heartbeat=now_ms,
        status="active",
        project_id=req.project_id,
    )
    await r.hset(k["nodes"], req.sessionID, node.model_dump_json())
    await r.set(_session_key(req.sessionID), bridge_id)
    if req.slug:
        await r.set(_slug_key(req.slug), bridge_id)
    await r.set(k["limit"], str(req.limit))
    await r.publish(k["channel"], json.dumps({"type": "node.joined", "node": node.model_dump()}))

    return await _build_info(bridge_id)


async def set_friend(req: SetFriendRequest) -> BridgeInfo:
    r = _get_client()

    master_id = req.masterIDOrSlug
    if not master_id.startswith("ses_"):
        resolved = await r.get(_slug_key(master_id))
        if not resolved:
            raise ValueError(f"Bridge master not found for slug: {master_id}")
        master_id = resolved

    k = _keys(master_id)
    if not await r.exists(k["master"]):
        raise ValueError(f"Bridge master not found: {master_id}")

    limit = int(await r.get(k["limit"]) or "3")
    nodes = await get_nodes(master_id)
    if len(nodes) >= limit:
        raise ValueError(f"Bridge {master_id} is full (limit: {limit})")
    if any(n.directory == req.directory for n in nodes):
        raise ValueError(f"A node with directory {req.directory!r} is already in this bridge")

    now_ms = time.time() * 1000
    node = NodeInfo(
        nodeID=req.sessionID,
        role="friend",
        sessionID=req.sessionID,
        slug=req.slug,
        title=req.title,
        directory=req.directory,
        nodeURL=req.nodeURL,
        heartbeat=now_ms,
        status="locked",
        project_id=req.project_id,
    )
    await r.hset(k["nodes"], req.sessionID, node.model_dump_json())
    await r.set(_session_key(req.sessionID), master_id)
    await r.publish(k["channel"], json.dumps({"type": "node.joined", "node": node.model_dump()}))
    master_raw = await r.hgetall(k["master"])
    await slack.friend_joined(
        bridge_slug=master_raw.get("slug", master_id),
        friend_title=req.title or req.sessionID,
        friend_dir=req.directory,
    )
    return await _build_info(master_id)


async def leave(bridge_id: str, session_id: str) -> None:
    r = _get_client()
    if not bridge_id:
        bridge_id = await r.get(_session_key(session_id)) or ""
    if not bridge_id:
        return

    k = _keys(bridge_id)
    master_raw = await r.hgetall(k["master"])
    is_master = master_raw.get("sessionID") == session_id

    if is_master:
        await r.publish(k["channel"], json.dumps({"type": "bridge.closed"}))
        nodes_raw = await r.hvals(k["nodes"])
        for n_raw in nodes_raw:
            try:
                n = NodeInfo.model_validate_json(n_raw)
                await r.delete(_session_key(n.sessionID))
            except Exception:
                pass
        await r.delete(k["master"], k["nodes"], k["context"], k["limit"])
        if master_raw.get("slug"):
            await r.delete(_slug_key(master_raw["slug"]))
    else:
        node_raw = await r.hget(k["nodes"], session_id)
        node_title = session_id
        if node_raw:
            try:
                node_title = NodeInfo.model_validate_json(node_raw).title or session_id
            except Exception:
                pass
        await r.hdel(k["nodes"], session_id)
        await r.delete(_session_key(session_id))
        await r.publish(k["channel"], json.dumps({"type": "node.left", "nodeID": session_id}))
        await slack.node_left(node_title, bridge_id)


async def heartbeat(bridge_id: str, session_id: str) -> None:
    r = _get_client()
    if not bridge_id:
        bridge_id = await r.get(_session_key(session_id)) or ""
    if not bridge_id:
        return
    k = _keys(bridge_id)
    node_raw = await r.hget(k["nodes"], session_id)
    if not node_raw:
        return
    try:
        node = NodeInfo.model_validate_json(node_raw)
        node.heartbeat = time.time() * 1000
        await r.hset(k["nodes"], session_id, node.model_dump_json())
    except Exception as e:
        logger.warning("heartbeat failed for %s: %s", session_id, e)


async def share_context(bridge_id: str, session_id: str, entry: ContextEntry) -> None:
    r = _get_client()
    k = _keys(bridge_id)
    entry.nodeID = session_id
    entry.timestamp = time.time() * 1000
    raw = entry.model_dump_json()
    await r.lpush(k["context"], raw)
    await r.ltrim(k["context"], 0, CONTEXT_MAX - 1)
    await r.publish(k["channel"], json.dumps({"type": "context.shared", "entry": entry.model_dump()}))
    await slack.context_shared(entry.type, entry.role, bridge_id, entry.content)


def _task_key(bridge_id: str, to_node_id: str) -> str:
    return f"bridge:{bridge_id}:tasks:{to_node_id}"


async def push_task(req: PushTaskRequest) -> BridgeTask:
    r = _get_client()
    task = BridgeTask(
        from_session_id=req.fromSessionID,
        prompt=req.prompt,
        description=req.description,
    )
    await r.rpush(_task_key(req.bridgeID, req.toNodeID), task.model_dump_json())
    await r.publish(
        _keys(req.bridgeID)["channel"],
        json.dumps({"type": "task.pushed", "toNodeID": req.toNodeID, "task_id": task.task_id}),
    )
    # Resolve friend's directory for the notification
    friend_dir = req.toNodeID
    node_raw = await r.hget(_keys(req.bridgeID)["nodes"], req.toNodeID)
    if node_raw:
        try:
            friend_dir = NodeInfo.model_validate_json(node_raw).directory or req.toNodeID
        except Exception:
            pass
    await slack.task_pushed(req.description, task.task_id, friend_dir)
    return task


async def fetch_tasks(bridge_id: str, session_id: str) -> list[BridgeTask]:
    r = _get_client()
    key = _task_key(bridge_id, session_id)
    raw_tasks = await r.lrange(key, 0, -1)
    await r.delete(key)
    tasks = []
    for raw in raw_tasks:
        try:
            tasks.append(BridgeTask.model_validate_json(raw))
        except Exception:
            pass
    return tasks


async def get_session(session_id: str) -> dict | None:
    """Resolve session_id → bridge_id and check master liveness.

    Returns {bridge_id, role, active} or None if the session is unknown.
    active=False means the master's heartbeat has gone stale — the bridge
    is effectively broken.
    """
    r = _get_client()
    bridge_id = await r.get(_session_key(session_id))
    if not bridge_id:
        return None

    k = _keys(bridge_id)
    master_raw = await r.hgetall(k["master"])
    if not master_raw:
        return {"bridge_id": bridge_id, "role": None, "active": False, "reason": "master key missing"}

    # Check master liveness
    try:
        master_hb = float(master_raw.get("heartbeat", 0))
    except ValueError:
        master_hb = 0
    now_ms = time.time() * 1000
    master_alive = (now_ms - master_hb) < STALE_MS

    # Resolve this node's role
    node_raw = await r.hget(k["nodes"], session_id)
    role = None
    if node_raw:
        try:
            role = NodeInfo.model_validate_json(node_raw).role
        except Exception:
            pass

    if not master_alive:
        return {"bridge_id": bridge_id, "role": role, "active": False, "reason": "master heartbeat stale"}

    return {"bridge_id": bridge_id, "role": role, "active": True}


async def get_info(bridge_id: str) -> BridgeInfo | None:
    r = _get_client()
    k = _keys(bridge_id)
    if not await r.exists(k["master"]):
        return None
    return await _build_info(bridge_id)


async def get_nodes(bridge_id: str) -> list[NodeInfo]:
    r = _get_client()
    k = _keys(bridge_id)
    nodes_raw = await r.hvals(k["nodes"])
    now_ms = time.time() * 1000
    nodes = []
    for raw in nodes_raw:
        try:
            n = NodeInfo.model_validate_json(raw)
            if now_ms - n.heartbeat < STALE_MS:
                nodes.append(n)
        except Exception:
            pass
    return nodes


async def get_context(bridge_id: str, limit: int = 50) -> list[ContextEntry]:
    r = _get_client()
    k = _keys(bridge_id)
    limit = min(limit, CONTEXT_MAX)
    raw_entries = await r.lrange(k["context"], 0, limit - 1)
    entries = []
    for raw in raw_entries:
        try:
            entries.append(ContextEntry.model_validate_json(raw))
        except Exception:
            pass
    return entries


async def list_bridges() -> list[BridgeInfo]:
    r = _get_client()
    cursor = 0
    bridge_ids: list[str] = []
    while True:
        cursor, keys = await r.scan(cursor, match="bridge:*:master", count=500)
        for key in keys:
            parts = key.split(":")
            if len(parts) == 3:
                bridge_ids.append(parts[1])
        if cursor == 0:
            break

    bridges = []
    for bid in bridge_ids:
        info = await get_info(bid)
        if info and info.nodes:
            bridges.append(info)
    return bridges


async def _build_info(bridge_id: str) -> BridgeInfo:
    r = _get_client()
    k = _keys(bridge_id)
    master_raw = await r.hgetall(k["master"])
    limit_raw = await r.get(k["limit"])
    nodes = await get_nodes(bridge_id)
    return BridgeInfo(
        bridgeID=bridge_id,
        masterID=master_raw.get("sessionID", bridge_id),
        masterSlug=master_raw.get("slug", ""),
        nodes=nodes,
        limit=int(limit_raw or "3"),
    )
