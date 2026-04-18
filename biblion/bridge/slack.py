"""Slack webhook notifications for bridge events that need user action."""
from __future__ import annotations
import logging
import httpx
from biblion import config

logger = logging.getLogger(__name__)


async def notify(text: str, context: str = "") -> None:
    """POST to the Slack webhook. Silently ignored if not configured."""
    url = config.SLACK_WEBHOOK_URL
    if not url:
        return
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if context:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context}],
        })
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(url, json={"blocks": blocks})
    except Exception as e:
        logger.warning("Slack notify failed: %s", e)


# ─── Event helpers (called via asyncio.create_task — non-blocking) ─────────────

async def friend_joined(bridge_slug: str, friend_title: str, friend_dir: str) -> None:
    await notify(
        f":busts_in_silhouette: *Friend joined* bridge `{bridge_slug or '(unnamed)'}`",
        f"{friend_title} · `{friend_dir}`",
    )


async def node_left(node_title: str, bridge_id: str) -> None:
    await notify(
        f":door: *{node_title}* left bridge `{bridge_id[:12]}…`",
    )


async def task_pushed(description: str, task_id: str, to_dir: str) -> None:
    await notify(
        f":inbox_tray: *Task queued for friend* — action needed",
        f"_{description or 'no description'}_ · task `{task_id[:8]}` · friend dir `{to_dir}`\n"
        f"Run `bridge_fetch_tasks` in the friend session to pick it up.",
    )


async def indexing_done(project_id: str, indexed: int, skipped: int, deleted: int, errors: int) -> None:
    icon = ":white_check_mark:" if not errors else ":warning:"
    detail = f"indexed {indexed} chunks · skipped {skipped}"
    if deleted:
        detail += f" · deleted {deleted}"
    if errors:
        detail += f" · *{errors} errors*"
    await notify(
        f"{icon} *Indexing complete* — `{project_id}`",
        detail,
    )


async def context_shared(entry_type: str, from_role: str, bridge_id: str, preview: str) -> None:
    if entry_type == "task_result":
        await notify(
            f":white_check_mark: *Task result ready* — action needed",
            f"Bridge `{bridge_id[:12]}…` · from {from_role}\n"
            f"Run `bridge_get_context` in the master session to read it.\n"
            f"> {preview[:120]}{'…' if len(preview) > 120 else ''}",
        )
    else:
        await notify(
            f":speech_balloon: *{from_role.capitalize()} shared context* (`{entry_type}`)",
            f"Bridge `{bridge_id[:12]}…` · `{preview[:120]}{'…' if len(preview) > 120 else ''}`",
        )
