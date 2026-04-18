"""Qdrant vector storage backend — pure HTTP, no SDK."""
from __future__ import annotations
import uuid
import httpx
from biblion import config


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if config.QDRANT_API_KEY:
        h["api-key"] = config.QDRANT_API_KEY
    return h


def _url(path: str) -> str:
    return f"{config.QDRANT_URL}{path}"


async def check_health() -> bool:
    """Return True if Qdrant is reachable, False otherwise."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_url("/healthz"), headers=_headers())
            resp.raise_for_status()
            return True
    except Exception:
        return False


async def ensure_collection(dim: int) -> None:
    """Create collection if it doesn't exist."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            _url(f"/collections/{config.COLLECTION_NAME}"),
            headers=_headers(),
        )
        if r.status_code == 404:
            await client.put(
                _url(f"/collections/{config.COLLECTION_NAME}"),
                headers=_headers(),
                json={"vectors": {"size": dim, "distance": "Cosine"}},
            )


async def upsert(points: list[dict]) -> None:
    """Insert or update points."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            _url(f"/collections/{config.COLLECTION_NAME}/points"),
            headers=_headers(),
            json={"points": points},
        )
        resp.raise_for_status()


async def search(
    vector: list[float],
    top_k: int,
    project_id: str = "",
) -> list[dict]:
    """Return top_k hits with payload and score."""
    body: dict = {
        "vector": vector,
        "limit": top_k,
        "with_payload": True,
    }
    if project_id:
        body["filter"] = {
            "must": [{"key": "project_id", "match": {"value": project_id}}]
        }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/search"),
            headers=_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])


async def scroll_all(project_id: str = "") -> list[dict]:
    """Page through all points and return them."""
    results = []
    offset = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            body: dict = {"limit": 100, "with_payload": True, "with_vector": False}
            if offset:
                body["offset"] = offset
            if project_id:
                body["filter"] = {
                    "must": [{"key": "project_id", "match": {"value": project_id}}]
                }
            resp = await client.post(
                _url(f"/collections/{config.COLLECTION_NAME}/points/scroll"),
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json().get("result", {})
            results.extend(data.get("points", []))
            offset = data.get("next_page_offset")
            if not offset:
                break
    return results


async def delete_by_id(point_id: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/delete"),
            headers=_headers(),
            json={"points": [point_id]},
        )
        resp.raise_for_status()


async def delete_by_project(project_id: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/delete"),
            headers=_headers(),
            json={"filter": {"must": [{"key": "project_id", "match": {"value": project_id}}]}},
        )
        resp.raise_for_status()


async def delete_all() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/delete"),
            headers=_headers(),
            json={"filter": {}},
        )
        resp.raise_for_status()


async def update_payload(point_id: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/payload"),
            headers=_headers(),
            json={"payload": payload, "points": [point_id]},
        )
        resp.raise_for_status()


async def count() -> int:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _url(f"/collections/{config.COLLECTION_NAME}/points/count"),
            headers=_headers(),
            json={"exact": True},
        )
        resp.raise_for_status()
        return resp.json().get("result", {}).get("count", 0)
