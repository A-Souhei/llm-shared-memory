"""Session identity — stores only session_id locally; bridge_id is resolved live from the server.

Each machine keeps its own session_id in ~/.biblion/session_id (or via
BIBLION_SESSION_ID env var). The bridge_id and role are always fetched from
the biblion server so this works transparently across machines and supports
multiple independent bridges.
"""
from __future__ import annotations
import os
import uuid
from pathlib import Path
from mcp_server import client

_ID_FILE = Path(os.environ.get("BIBLION_SESSION_FILE", Path.home() / ".biblion" / "session_id"))


def load_session_id() -> str:
    env = os.environ.get("BIBLION_SESSION_ID", "")
    if env:
        return env
    try:
        return _ID_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def save_session_id(session_id: str) -> None:
    _ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ID_FILE.write_text(session_id)


def clear_session_id() -> None:
    try:
        _ID_FILE.unlink()
    except FileNotFoundError:
        pass


def new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:12]}"


async def resolve() -> tuple[str, str]:
    """Return (bridge_id, session_id) by asking the server.

    Raises ValueError with a clear message if:
    - no session_id is stored locally
    - the server doesn't recognise this session
    - the master heartbeat has gone stale (bridge broken)
    """
    session_id = load_session_id()
    if not session_id:
        raise ValueError(
            "No active session. Call bridge_set_master or bridge_set_friend first."
        )

    data = await client.get_json("/bridge/session", session_id=session_id)

    if not data.get("active"):
        reason = data.get("reason", "unknown")
        raise ValueError(
            f"Bridge is no longer active ({reason}). "
            "Call bridge_set_master or bridge_set_friend to start a new one."
        )

    return data["bridge_id"], session_id


async def role() -> str:
    """Return the role ('master' or 'friend') for the current session."""
    session_id = load_session_id()
    if not session_id:
        return "unknown"
    try:
        data = await client.get_json("/bridge/session", session_id=session_id)
        return data.get("role") or "unknown"
    except Exception:
        return "unknown"
