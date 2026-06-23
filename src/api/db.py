"""
API-local asyncpg pool.

The FastAPI service runs in a SEPARATE process from the Temporal worker, so it
maintains its own connection pool. This is intentionally NOT shared with
``src.activities.db_activities._pool`` (that pool lives in the worker process).
"""
from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

_api_pool: asyncpg.Pool | None = None


async def init_api_pool(dsn: str) -> asyncpg.Pool:
    """Create and store the module-level API connection pool."""
    global _api_pool
    if _api_pool is None:
        _api_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("API asyncpg pool created (min=2, max=10)")
    return _api_pool


async def close_api_pool() -> None:
    global _api_pool
    if _api_pool is not None:
        await _api_pool.close()
        _api_pool = None
        logger.info("API asyncpg pool closed")


def get_api_pool() -> asyncpg.Pool:
    if _api_pool is None:
        raise RuntimeError(
            "API database pool has not been initialised. Call init_api_pool() first."
        )
    return _api_pool
