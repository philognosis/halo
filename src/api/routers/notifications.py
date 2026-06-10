"""Notification endpoints (inbox, mark-read, unread count)."""
from __future__ import annotations

import json

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_pool

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _row_to_notification(row: asyncpg.Record) -> dict:
    result = dict(row)
    meta = result.get("metadata")
    if isinstance(meta, str):
        try:
            result["metadata"] = json.loads(meta)
        except (TypeError, ValueError):
            result["metadata"] = None
    return result


@router.get("/{person_id}")
async def list_notifications(
    person_id: str,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    unread_clause = "AND is_read = false" if unread_only else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id::TEXT, event_id::TEXT, recipient_id::TEXT, type,
                   title, body, metadata, is_read, read_at::TEXT,
                   created_at::TEXT, expires_at::TEXT
            FROM notification
            WHERE recipient_id = $1::UUID {unread_clause}
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            person_id,
            limit,
            offset,
        )
    return [_row_to_notification(r) for r in rows]


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE notification
               SET is_read = true, read_at = NOW()
             WHERE id = $1::UUID
            RETURNING id::TEXT, event_id::TEXT, recipient_id::TEXT, type,
                      title, body, metadata, is_read, read_at::TEXT,
                      created_at::TEXT, expires_at::TEXT
            """,
            notification_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return _row_to_notification(row)


@router.get("/{person_id}/unread-count")
async def unread_count(
    person_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM notification
            WHERE recipient_id = $1::UUID AND is_read = false
            """,
            person_id,
        )
    return {"person_id": person_id, "unread_count": int(count or 0)}
