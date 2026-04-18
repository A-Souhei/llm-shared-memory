"""Pydantic models for bridge mode."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
import time
import uuid

NodeRole = Literal["master", "friend"]
NodeStatus = Literal["active", "inactive", "stale"]
ContextType = Literal["finding", "work_summary", "task_result", "status"]


class NodeInfo(BaseModel):
    nodeID: str
    role: NodeRole
    sessionID: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    nodeURL: str = ""
    heartbeat: float = Field(default_factory=lambda: time.time() * 1000)
    status: NodeStatus = "active"
    project_id: str = ""


class BridgeInfo(BaseModel):
    bridgeID: str
    masterID: str
    masterSlug: str = ""
    nodes: list[NodeInfo]
    limit: int
    createdAt: float = Field(default_factory=lambda: time.time() * 1000)


class ContextEntry(BaseModel):
    nodeID: str = ""
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
    sessionID: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    nodeURL: str = ""
    limit: int = 3
    project_id: str = ""


class SetFriendRequest(BaseModel):
    masterIDOrSlug: str
    sessionID: str
    slug: str = ""
    title: str = ""
    directory: str = ""
    nodeURL: str = ""
    project_id: str = ""


class LeaveRequest(BaseModel):
    bridgeID: str = ""
    sessionID: str


class ShareContextRequest(BaseModel):
    bridgeID: str
    sessionID: str
    role: NodeRole
    directory: str = ""
    type: ContextType
    content: str


class PushTaskRequest(BaseModel):
    bridgeID: str
    fromSessionID: str
    toNodeID: str
    prompt: str
    description: str = ""


class HeartbeatRequest(BaseModel):
    bridgeID: str
    sessionID: str
