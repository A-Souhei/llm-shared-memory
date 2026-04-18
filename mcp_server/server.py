"""Biblion MCP server — bridge, biblion, and indexer tools for AI agents."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP
from mcp_server import client

mcp = FastMCP(
    "biblion",
    instructions=(
        "Tools for the biblion nexus: manage bridge sessions between AI agents, "
        "read/write the shared knowledge base, and search indexed codebases."
    ),
)

# ─── Bridge tools ──────────────────────────────────────────────────────────────
# Flow:
#   master  → bridge_set_master  (register)
#   friend  → bridge_set_friend  (join)
#   master  → bridge_push_task   (queue a prompt for a friend)
#   friend  → bridge_fetch_tasks (dequeue and run)
#   friend  → bridge_share_context type=task_result (store result)
#   master  → bridge_get_context (read results)
#   either  → bridge_heartbeat   (keep node alive, call every ~15s)
#   either  → bridge_leave       (clean exit)


@mcp.tool()
async def bridge_set_master(
    session_id: str,
    slug: str = "",
    title: str = "",
    directory: str = "",
    node_url: str = "",
    limit: int = 3,
    project_id: str = "",
) -> str:
    """Register this agent as the bridge master.

    Call once when starting a master session. The returned bridgeID is the
    session_id itself — share it with friends via bridge_set_friend.

    Args:
        session_id: Unique identifier for this session (e.g. "ses_abc123").
        slug: Human-readable name for this bridge (used by friends to join).
        title: Display name shown in the web UI.
        directory: Working directory of this agent.
        node_url: HTTP URL this node is reachable at (cross-machine only).
        limit: Max total nodes (master + friends). Default 3.
        project_id: Project identifier, e.g. the repo name.
    """
    data = await client.post_json("/bridge/set-master", {
        "sessionID": session_id,
        "slug": slug,
        "title": title,
        "directory": directory,
        "nodeURL": node_url,
        "limit": limit,
        "project_id": project_id,
    })
    info = data
    nodes = info.get("nodes", [])
    return (
        f"Bridge created. bridgeID={info['bridgeID']} slug={info.get('masterSlug', '')} "
        f"nodes={len(nodes)}/{info['limit']}"
    )


@mcp.tool()
async def bridge_set_friend(
    master_id_or_slug: str,
    session_id: str,
    slug: str = "",
    title: str = "",
    directory: str = "",
    node_url: str = "",
    project_id: str = "",
) -> str:
    """Join an existing bridge as a friend node.

    Args:
        master_id_or_slug: The master's session_id or slug to join.
        session_id: Unique identifier for this friend session.
        slug: Human-readable name for this friend node.
        title: Display name shown in the web UI.
        directory: Working directory of this friend agent.
        node_url: HTTP URL this node is reachable at (cross-machine only).
        project_id: Project identifier for this friend's codebase.
    """
    data = await client.post_json("/bridge/set-friend", {
        "masterIDOrSlug": master_id_or_slug,
        "sessionID": session_id,
        "slug": slug,
        "title": title,
        "directory": directory,
        "nodeURL": node_url,
        "project_id": project_id,
    })
    info = data
    return (
        f"Joined bridge {info['bridgeID']}. "
        f"Nodes: {', '.join(n['slug'] or n['nodeID'] for n in info.get('nodes', []))}"
    )


@mcp.tool()
async def bridge_leave(bridge_id: str, session_id: str) -> str:
    """Leave the bridge cleanly.

    If the master leaves, all bridge state is deleted. If a friend leaves, only
    that friend's entry is removed.

    Args:
        bridge_id: The bridgeID (can be empty string — resolved from session_id).
        session_id: This node's session ID.
    """
    await client.post_json("/bridge/leave", {
        "bridgeID": bridge_id,
        "sessionID": session_id,
    })
    return "Left bridge."


@mcp.tool()
async def bridge_heartbeat(bridge_id: str, session_id: str) -> str:
    """Update this node's liveness timestamp.

    Call roughly every 15 seconds. Nodes not heard from in 60 seconds are
    considered stale and hidden from the active node list.

    Args:
        bridge_id: The current bridgeID.
        session_id: This node's session ID.
    """
    await client.post_json("/bridge/heartbeat", {
        "bridgeID": bridge_id,
        "sessionID": session_id,
    })
    return "Heartbeat sent."


@mcp.tool()
async def bridge_get_info(bridge_id: str) -> str:
    """Get the current state of a bridge: all nodes, their roles, directories, and status.

    Args:
        bridge_id: The bridgeID to inspect.
    """
    data = await client.get_json("/bridge/info", bridge_id=bridge_id)
    if not data:
        return "Bridge not found or no active nodes."
    nodes = data.get("nodes", [])
    lines = [
        f"Bridge {data['bridgeID']} (slug: {data.get('masterSlug', '-')}) "
        f"— {len(nodes)}/{data['limit']} nodes"
    ]
    for n in nodes:
        age_s = int((__import__("time").time() * 1000 - n["heartbeat"]) / 1000)
        lines.append(
            f"  [{n['role']}] {n.get('slug') or n['nodeID']} "
            f"dir={n['directory']} project={n.get('project_id', '-')} "
            f"heartbeat={age_s}s ago status={n['status']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def bridge_push_task(
    bridge_id: str,
    from_session_id: str,
    to_node_id: str,
    prompt: str,
    description: str = "",
) -> str:
    """Push a task (prompt) to a friend node's queue.

    The friend will dequeue it when they call bridge_fetch_tasks. Results are
    returned via bridge_share_context with type=task_result.

    Args:
        bridge_id: The current bridgeID.
        from_session_id: The master's session ID.
        to_node_id: The target friend's nodeID (session ID or slug).
        prompt: The full prompt / instructions for the friend to execute.
        description: Short human-readable summary of the task.
    """
    data = await client.post_json("/bridge/push-task", {
        "bridgeID": bridge_id,
        "fromSessionID": from_session_id,
        "toNodeID": to_node_id,
        "prompt": prompt,
        "description": description,
    })
    return f"Task queued. task_id={data['task_id']} for node {to_node_id}"


@mcp.tool()
async def bridge_fetch_tasks(bridge_id: str, session_id: str) -> str:
    """Fetch and consume all pending tasks queued for this node.

    Returns the full list of tasks (including their prompts) and clears the
    queue. Run each prompt in your current directory, then call
    bridge_share_context with type=task_result to return results.

    Args:
        bridge_id: The current bridgeID.
        session_id: This friend node's session ID.
    """
    data = await client.get_json(
        "/bridge/fetch-tasks",
        bridge_id=bridge_id,
        session_id=session_id,
    )
    tasks = data if isinstance(data, list) else []
    if not tasks:
        return "No pending tasks."
    lines = [f"{len(tasks)} task(s) received:"]
    for t in tasks:
        lines.append(f"\n--- task_id={t['task_id']} ({t.get('description', '')}) ---")
        lines.append(t["prompt"])
    return "\n".join(lines)


@mcp.tool()
async def bridge_share_context(
    bridge_id: str,
    session_id: str,
    role: str,
    type: str,
    content: str,
    directory: str = "",
) -> str:
    """Share a context entry with all bridge participants.

    Use type=task_result to return task output to the master.
    Use type=finding for discoveries, type=status for progress updates.

    Args:
        bridge_id: The current bridgeID.
        session_id: This node's session ID.
        role: "master" or "friend".
        type: One of: finding, work_summary, task_result, status.
        content: The content to share. For task results, include the task_id
                 at the start: "task_id: <id>\\n<result>".
        directory: Working directory of the node sharing this entry.
    """
    await client.post_json("/bridge/share-context", {
        "bridgeID": bridge_id,
        "sessionID": session_id,
        "role": role,
        "type": type,
        "content": content,
        "directory": directory,
    })
    return f"Context shared (type={type})."


@mcp.tool()
async def bridge_get_context(bridge_id: str, limit: int = 20) -> str:
    """Retrieve recent shared context entries from the bridge.

    Use this to read results from friends, shared findings, or status updates.
    Entries are returned newest-first.

    Args:
        bridge_id: The current bridgeID.
        limit: Number of entries to return (1-200, default 20).
    """
    data = await client.get_json("/bridge/context", bridge_id=bridge_id, limit=limit)
    entries = data if isinstance(data, list) else []
    if not entries:
        return "No context entries."
    lines = [f"{len(entries)} entries (newest first):"]
    for e in entries:
        ts = e.get("timestamp", 0)
        age_s = int((__import__("time").time() * 1000 - ts) / 1000)
        lines.append(
            f"\n[{e['type']}] {e.get('role', '?')} @ {e.get('directory', '-')} ({age_s}s ago)"
        )
        lines.append(e["content"][:500] + ("…" if len(e["content"]) > 500 else ""))
    return "\n".join(lines)


# ─── Biblion tools ─────────────────────────────────────────────────────────────


@mcp.tool()
async def biblion_search(query: str, limit: int = 5, project_id: str = "") -> str:
    """Search the semantic knowledge base for relevant entries.

    Args:
        query: Natural language query describing what you're looking for.
        limit: Max results (1-50, default 5).
        project_id: Narrow to a specific project, or leave empty for all projects.
    """
    # TODO: implement in next session
    raise NotImplementedError("biblion_search — implement in next session")


@mcp.tool()
async def biblion_write(
    type: str,
    content: str,
    tags: list[str] | None = None,
    project_id: str = "",
) -> str:
    """Write a knowledge entry to the biblion knowledge base.

    Args:
        type: Entry type: structure, pattern, dependency, api, config, or workflow.
        content: The knowledge to store (max 50 000 chars).
        tags: Optional list of tags (auto-generated tags are merged in).
        project_id: Project this entry belongs to.
    """
    # TODO: implement in next session
    raise NotImplementedError("biblion_write — implement in next session")


@mcp.tool()
async def biblion_list(project_id: str = "") -> str:
    """List all knowledge base entries, optionally filtered by project.

    Args:
        project_id: Filter to a specific project, or leave empty for all.
    """
    # TODO: implement in next session
    raise NotImplementedError("biblion_list — implement in next session")


# ─── Indexer tools ─────────────────────────────────────────────────────────────


@mcp.tool()
async def indexer_search(query: str, project_id: str, top_k: int = 5) -> str:
    """Search indexed source code by semantic similarity.

    Args:
        query: What you're looking for in the codebase.
        project_id: The project to search (required — code index is per-project).
        top_k: Number of code chunks to return (1-50, default 5).
    """
    # TODO: implement in next session
    raise NotImplementedError("indexer_search — implement in next session")


@mcp.tool()
async def indexer_ingest(directory: str, project_id: str) -> str:
    """Ingest a directory into the code index for semantic search.

    Args:
        directory: Absolute path to the directory to index.
        project_id: Project identifier for this codebase.
    """
    # TODO: implement in next session
    raise NotImplementedError("indexer_ingest — implement in next session")


def run():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
