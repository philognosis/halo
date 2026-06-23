"""Health and readiness endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Response
from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client

from src.api.dependencies import get_pool, get_sparql, get_temporal
from src.bridge.sparql_client import SparqlClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(
    response: Response,
    pool: asyncpg.Pool = Depends(get_pool),
    temporal: Client = Depends(get_temporal),
    sparql: SparqlClient = Depends(get_sparql),
) -> dict[str, object]:
    checks: dict[str, str] = {}

    # --- Postgres ---
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        checks["database"] = f"down: {exc}"

    # --- Temporal ---
    try:
        await temporal.workflow_service.get_system_info(GetSystemInfoRequest())
        checks["temporal"] = "ok"
    except Exception as exc:
        checks["temporal"] = f"down: {exc}"

    # --- Fuseki ---
    try:
        ok = await sparql.ask("ASK {}")
        checks["fuseki"] = "ok" if ok else "down: ASK returned false"
    except Exception as exc:
        checks["fuseki"] = f"down: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
