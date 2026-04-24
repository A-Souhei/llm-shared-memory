"""Pydantic models for API request/response and internal data."""
from __future__ import annotations
from typing import Literal, Union
from pydantic import BaseModel, Field
import time
import uuid

EntryType = Literal["structure", "pattern", "dependency", "api", "config", "workflow", "memento"]

DisabledReason = Literal[
    "redis_unreachable",
    "embedding_unreachable",
    "error",
]


class StatusDisabled(BaseModel):
    type: Literal["disabled"] = "disabled"
    reason: DisabledReason
    message: str = ""


class StatusReady(BaseModel):
    type: Literal["ready"] = "ready"
    entry_count: int
    token_count: int
    redis_url: str
    embedding_url: str
    embedding_model: str


Status = Union[StatusReady, StatusDisabled]


class WriteRequest(BaseModel):
    type: EntryType
    content: str = Field(..., max_length=50_000)
    tags: list[str] = Field(default_factory=list)
    session_id: str = ""
    branch: str = ""
    quality: float = Field(default=5.0, ge=0, le=10)
    project_id: str = ""


class BiblionEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EntryType
    content: str
    query: str = ""
    tags: list[str] = Field(default_factory=list)
    session_id: str = ""
    branch: str = ""
    quality: float = 0.5          # stored 0-1
    used_count: int = 0
    token_count: int = 0
    timestamp: float = Field(default_factory=time.time)
    project_id: str = ""


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=100)
    project_id: str = ""


class SearchResult(BaseModel):
    id: str
    type: EntryType
    content: str
    tags: list[str]
    quality: float
    used_count: int
    similarity: float
    score: float
    project_id: str = ""


class ListEntry(BaseModel):
    id: str
    type: EntryType
    tags: str          # comma-joined for compact display
    content: str
    project_id: str = ""


class WriteResponse(BaseModel):
    success: bool
    id: str = ""
    reason: str = ""


class MementoSaveRequest(BaseModel):
    content: str = Field(..., max_length=50_000)
    project_id: str


class MementoEntry(BaseModel):
    id: str
    content: str
    project_id: str
    created_at: str
