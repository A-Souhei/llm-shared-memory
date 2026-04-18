"""Pydantic models for bridge mode — all fields use snake_case."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
import time
import uuid

NodeRole = Literal["master", "friend"]
NodeStatus = Literal["active", "inactive", "stale"]
ContextType = Literal["finding", "work_summary", "task_result", "status"]


class NodeInfo(BaseModel):
    node_id: str
    role: NodeRole
    session_id: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    node_url: str = ""
    heartbeat: float = Field(default_factory=lambda: time.time() * 1000)
    status: NodeStatus = "active"
    project_id: str = ""


class BridgeInfo(BaseModel):
    bridge_id: str
    master_id: str
    master_slug: str = ""
    nodes: list[NodeInfo]
    limit: int
    created_at: float = Field(default_factory=lambda: time.time() * 1000)


class ContextEntry(BaseModel):
    node_id: str = ""
    role: NodeRole = "master"
    directory: str = ""
    type: ContextType
    content: str
    timestamp: float = Field(default_factory=lambda: time.time() * 1000)


class BridgeTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_session_id: str
    prompt: str
    description: str = ""
    timestamp: float = Field(default_factory=lambda: time.time() * 1000)


class SetMasterRequest(BaseModel):
    session_id: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    node_url: str = ""
    limit: int = 3
    project_id: str = ""


class SetFriendRequest(BaseModel):
    master_id_or_slug: str
    session_id: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    node_url: str = ""
    project_id: str = ""


class LeaveRequest(BaseModel):
    bridge_id: str = ""
    session_id: str


class ShareContextRequest(BaseModel):
    bridge_id: str
    session_id: str
    role: NodeRole
    directory: str = ""
    type: ContextType
    content: str


class PushTaskRequest(BaseModel):
    bridge_id: str
    from_session_id: str
    to_node_id: str
    prompt: str
    description: str = ""


class HeartbeatRequest(BaseModel):
    bridge_id: str
    session_id: str
