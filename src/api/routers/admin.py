"""Admin / operational endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends

from src.api.dependencies import get_pool, get_sparql
from src.bridge.abox_sync import ABOX_GRAPH_URI, sync_abox
from src.bridge.sparql_client import SparqlClient

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync-abox")
async def trigger_abox_sync(
    pool: asyncpg.Pool = Depends(get_pool),
    sparql: SparqlClient = Depends(get_sparql),
) -> dict:
    """Manually trigger a Postgres → Jena ABox projection."""
    result = await sync_abox(pool, sparql, ABOX_GRAPH_URI)
    return result
