from __future__ import annotations
import re
from pydantic import BaseModel, Field, field_validator
from typing import Any

_PROJECT_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,128}$')


def _validate_project_id(v: str) -> str:
    if not _PROJECT_ID_RE.match(v):
        raise ValueError("project_id must be 1–128 alphanumeric/dash/underscore characters")
    return v


class IndexerStatus(BaseModel):
    status: str  # "ok" | "disabled"
    reason: str | None = None
    redis_url: str | None = None
    projects: list[str] = Field(default_factory=list)


class IndexerProjectStats(BaseModel):
    project_id: str
    chunk_count: int
    file_count: int


class FileInput(BaseModel):
    path: str       # relative path within the project
    content: str
    mtime: float    # ms since epoch (st_mtime_ns / 1e6)


class IngestRequest(BaseModel):
    project_id: str
    files: list[FileInput]              # new or changed files (with content)
    all_paths: list[str] | None = None  # all current paths — enables deletion detection; None = skip

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, v: str) -> str:
        return _validate_project_id(v)


class StartRequest(BaseModel):
    project_id: str
    source_dir: str


class StartResponse(BaseModel):
    project_id: str
    indexed: int
    skipped: int
    deleted: int
    errors: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    project_id: str
    top_k: int = 10
    min_score: float = 0.35

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, v: str) -> str:
        return _validate_project_id(v)


class SearchResult(BaseModel):
    file_path: str
    start_line: int
    text: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class ClearRequest(BaseModel):
    project_id: str

    @field_validator("project_id")
    @classmethod
    def check_project_id(cls, v: str) -> str:
        return _validate_project_id(v)


class IndexerProgressJob(BaseModel):
    project_id: str
    processed: int
    total: int
