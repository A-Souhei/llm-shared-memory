"""Ollama-compatible embedding service."""
from __future__ import annotations
import httpx
from biblion import config

_dim: int | None = None

async def embed(text: str) -> list[float]:
    """Return embedding vector for text. Raises on failure."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{config.EMBEDDING_URL}/api/embeddings",
            json={"model": config.EMBEDDING_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


async def get_dim() -> int:
    """Return embedding dimension (cached after first call)."""
    global _dim
    if _dim is None:
        vec = await embed("dim")
        _dim = len(vec)
    return _dim


async def check_health() -> bool:
    """Return True if embedding server is reachable, False otherwise."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{config.EMBEDDING_URL}/api/tags")
            resp.raise_for_status()
            return True
    except Exception:
        return False
