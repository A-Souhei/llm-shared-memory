"""Hybrid scoring: similarity * 0.7 + usage * 0.2 + quality * 0.1."""
from __future__ import annotations
import math
from biblion import config


def normalize_used(count: int, max_count: int) -> float:
    if max_count <= 0:
        return 0.0
    return math.log(1 + count) / math.log(1 + max_count)


def score(
    similarity: float,
    used_count: int,
    max_used: int,
    quality: float,
) -> float:
    norm_used = normalize_used(used_count, max_used)
    norm_quality = max(0.0, min(1.0, quality))
    return (
        similarity * config.SIMILARITY_WEIGHT
        + norm_used * config.USAGE_WEIGHT
        + norm_quality * config.QUALITY_WEIGHT
    )


def rank(entries: list[dict]) -> list[dict]:
    """Add 'score' field and sort descending. Each entry must have similarity, used_count, quality."""
    if not entries:
        return entries
    max_used = max(e.get("used_count", 0) for e in entries) or 1
    for e in entries:
        e["score"] = score(
            e.get("similarity", 0.0),
            e.get("used_count", 0),
            max_used,
            e.get("quality", config.DEFAULT_QUALITY),
        )
    return sorted(entries, key=lambda e: e["score"], reverse=True)
