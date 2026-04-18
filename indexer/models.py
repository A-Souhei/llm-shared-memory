from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any


class IndexerStatus(BaseModel):
    status: str  # "ok" | "disabled"
    reason: str | None = None
    redis_url: str | None = None
    projects: list[str] = Field(default_factory=list)


class FileInput(BaseModel):
    path: str       # relative path within the project
    content: str
    mtime: float    # ms since epoch (st_mtime_ns / 1e6)


class IngestRequest(BaseModel):
    project_id: str
    files: list[FileInput]      # new or changed files (with content)
    all_paths: list[str] = []   # all current paths — enables deletion detection


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


class SearchResult(BaseModel):
    file_path: str
    start_line: int
    text: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class ClearRequest(BaseModel):
    project_id: str
