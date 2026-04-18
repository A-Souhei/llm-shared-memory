"""Biblion MCP server — bridge, biblion, and indexer tools for AI agents."""
from __future__ import annotations
import os
import time
from mcp.server.fastmcp import FastMCP
from mcp_server import client, session as sess

mcp = FastMCP(
    "biblion",
    instructions=(
        "Tools for the biblion nexus: manage bridge sessions between AI agents, "
        "read/write the shared knowledge base, and search indexed codebases. "
        "After calling bridge_set_master or bridge_set_friend the session is "
        "remembered automatically — you do not need to pass bridge_id or "
        "session_id to subsequent tools unless you are managing multiple bridges."
    ),
)


@mcp.on_shutdown
async def _shutdown():
    await client.aclose()


# ─── Bridge — session setup ────────────────────────────────────────────────────


@mcp.tool()
async def bridge_set_master(
    slug: str = "",
    title: str = "",
    directory: str = "",
    node_url: str = "",
    limit: int = 3,
    project_id: str = "",
    session_id: str = "",
) -> str:
    """Register this agent as the bridge master.

    Creates a new bridge session and saves the session ID locally so you
    don't need to pass bridge_id or session_id to any subsequent bridge tools.

    Args:
        slug: Short human-readable name friends use to join (e.g. "frontend").
        title: Display name shown in the web UI.
        directory: Working directory of this agent (defaults to $PWD).
        node_url: Externally reachable HTTP URL — only needed cross-machine.
        limit: Max total nodes (master + friends). Default 3.
        project_id: Project identifier, e.g. the repo name.
        session_id: Override the auto-generated session ID (rarely needed).
    """
    sid = session_id or sess.new_session_id()
    directory = directory or os.environ.get("PWD", "")
    data = await client.post_json("/bridge/set-master", {
        "session_id": sid,
        "slug": slug,
        "title": title,
        "directory": directory,
        "node_url": node_url,
        "limit": limit,
        "project_id": project_id,
    })
    sess.save_session_id(sid)
    nodes = data.get("nodes", [])
    return (
        f"Bridge created — session ID saved.\n"
        f"bridge_id: {data['bridge_id']}\n"
        f"slug: {data.get('master_slug') or '(none)'}\n"
        f"nodes: {len(nodes)}/{data['limit']}\n"
        f"Share the bridge_id or slug so friends can join with bridge_set_friend."
    )


@mcp.tool()
async def bridge_set_friend(
    master_id_or_slug: str,
    slug: str = "",
    title: str = "",
    directory: str = "",
    node_url: str = "",
    project_id: str = "",
    session_id: str = "",
) -> str:
    """Join an existing bridge as a friend node.

    Saves the session ID locally so you don't need to pass bridge_id or
    session_id to subsequent bridge tools.

    Args:
        master_id_or_slug: The master's bridge_id or slug to join.
        slug: Short name for this friend node.
        title: Display name shown in the web UI.
        directory: Working directory of this friend agent (defaults to $PWD).
        node_url: Externally reachable HTTP URL — only needed cross-machine.
        project_id: Project identifier for this friend's codebase.
        session_id: Override the auto-generated session ID (rarely needed).
    """
    sid = session_id or sess.new_session_id()
    directory = directory or os.environ.get("PWD", "")
    data = await client.post_json("/bridge/set-friend", {
        "master_id_or_slug": master_id_or_slug,
        "session_id": sid,
        "slug": slug,
        "title": title,
        "directory": directory,
        "node_url": node_url,
        "project_id": project_id,
    })
    sess.save_session_id(sid)
    nodes = data.get("nodes", [])
    return (
        f"Joined bridge — session ID saved.\n"
        f"bridge_id: {data['bridge_id']}\n"
        f"nodes: {', '.join(n.get('slug') or n['node_id'] for n in nodes)}"
    )


@mcp.tool()
async def bridge_leave() -> str:
    """Leave the current bridge and clear the local session ID.

    If you are the master, the bridge is closed for all nodes.
    If you are a friend, only your node is removed.
    """
    session_id = sess.load_session_id()
    if not session_id:
        return "No active session."
    try:
        bridge_id, _ = await sess.resolve()
        await client.post_json("/bridge/leave", {
            "bridge_id": bridge_id,
            "session_id": session_id,
        })
    except ValueError:
        pass  # bridge already gone — still clear locally
    sess.clear_session_id()
    return "Left bridge. Local session ID cleared."


# ─── Bridge — daily use ────────────────────────────────────────────────────────


@mcp.tool()
async def bridge_heartbeat() -> str:
    """Update this node's liveness timestamp.

    Call roughly every 15 seconds to stay visible. Nodes not heard from in
    60 seconds are considered stale and hidden from the active node list.
    """
    bridge_id, session_id = await sess.resolve()
    await client.post_json("/bridge/heartbeat", {
        "bridge_id": bridge_id,
        "session_id": session_id,
    })
    return "Heartbeat sent."


@mcp.tool()
async def bridge_get_info() -> str:
    """Get the current bridge state: all nodes, their roles, directories, and heartbeat age."""
    bridge_id, _ = await sess.resolve()
    data = await client.get_json("/bridge/info", bridge_id=bridge_id)
    if not data:
        return "Bridge not found or no active nodes."
    nodes = data.get("nodes", [])
    lines = [
        f"Bridge {data['bridge_id']} (slug: {data.get('master_slug') or '-'}) "
        f"— {len(nodes)}/{data['limit']} nodes"
    ]
    for n in nodes:
        age_s = int((time.time() * 1000 - n["heartbeat"]) / 1000)
        lines.append(
            f"  [{n['role']}] {n.get('slug') or n['node_id']}  "
            f"dir={n['directory']}  project={n.get('project_id') or '-'}  "
            f"heartbeat={age_s}s ago  status={n['status']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def bridge_push_task(
    to_node_id: str,
    prompt: str,
    description: str = "",
) -> str:
    """Push a task (prompt) to a friend node's queue.

    The friend will see a Slack notification and dequeue it with
    bridge_fetch_tasks. Results come back via bridge_get_context.

    Args:
        to_node_id: The target friend's node_id. Use bridge_get_info to list nodes.
        prompt: The full prompt / instructions for the friend to execute.
        description: Short summary shown in the Slack notification.
    """
    bridge_id, session_id = await sess.resolve()
    data = await client.post_json("/bridge/push-task", {
        "bridge_id": bridge_id,
        "from_session_id": session_id,
        "to_node_id": to_node_id,
        "prompt": prompt,
        "description": description,
    })
    return f"Task queued. task_id={data['task_id']}"


@mcp.tool()
async def bridge_fetch_tasks() -> str:
    """Fetch and consume all tasks queued for this node.

    Clears the queue after reading. Execute each task in your working
    directory, then call bridge_share_context with type=task_result to
    return results to the master.
    """
    bridge_id, session_id = await sess.resolve()
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
    type: str,
    content: str,
    directory: str = "",
) -> str:
    """Share a context entry with all bridge participants.

    Use type=task_result to return task output to the master (triggers a
    Slack notification). Use type=finding for discoveries, type=status
    for progress updates.

    Args:
        type: One of: finding, work_summary, task_result, status.
        content: The content to share. For task results prefix with the
                 task_id: "task_id: <id>\\n<result>".
        directory: Override directory (server defaults to registered node directory).
    """
    bridge_id, session_id = await sess.resolve()
    current_role = await sess.role()
    await client.post_json("/bridge/share-context", {
        "bridge_id": bridge_id,
        "session_id": session_id,
        "role": current_role,
        "type": type,
        "content": content,
        "directory": directory,
    })
    return f"Context shared (type={type})."


@mcp.tool()
async def bridge_get_context(limit: int = 20) -> str:
    """Read recent shared context entries from the bridge (newest first).

    Use this to read results from friends after they've called
    bridge_share_context with type=task_result.

    Args:
        limit: Number of entries to return (1-200, default 20).
    """
    bridge_id, _ = await sess.resolve()
    data = await client.get_json("/bridge/context", bridge_id=bridge_id, limit=limit)
    entries = data if isinstance(data, list) else []
    if not entries:
        return "No context entries."
    lines = [f"{len(entries)} entries (newest first):"]
    for e in entries:
        age_s = int((time.time() * 1000 - e.get("timestamp", 0)) / 1000)
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
