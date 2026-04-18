"""Thin async HTTP client wrapping the biblion REST API."""
from __future__ import annotations
import os
import httpx

BASE_URL = os.environ.get("BIBLION_API_URL", "http://localhost:18765")

_client: httpx.AsyncClient | None = None


def get() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_json(path: str, **params) -> dict | list:
    r = await get().get(path, params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


async def post_json(path: str, body: dict) -> dict | list:
    r = await get().post(path, json=body)
    r.raise_for_status()
    return r.json()
