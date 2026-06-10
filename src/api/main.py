"""
FastAPI application for the Ontology-Driven Agentic Staffing System (Phase 2).

This is a SEPARATE process from the Temporal worker. It:
  - owns its own asyncpg pool (src.api.db)
  - connects its own Temporal client (string-based signals/queries only — it
    never imports the workflow classes, to avoid the workflow sandbox imports)
  - owns its own SparqlClient (the Python bridge to Jena)
  - runs a periodic Postgres → Jena ABox sync loop

The API relays human approve/reject decisions to durable Temporal workflows
(the HITL gates) and exposes the operational + semantic read models.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client

from src.api.db import close_api_pool, get_api_pool, init_api_pool
from src.api.routers import (
    admin,
    approvals,
    assignments,
    health,
    notifications,
    opportunities,
    persons,
    projects,
    teams,
)
from src.bridge.abox_sync import ABOX_GRAPH_URI, sync_abox
from src.bridge.sparql_client import SparqlClient
from src.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("staffing.api")


async def _abox_sync_loop(app: FastAPI) -> None:
    """Background loop: periodically project Postgres → Jena ABox."""
    interval = settings.ABOX_SYNC_INTERVAL_SECONDS
    if interval <= 0:
        logger.info("ABox sync loop disabled (ABOX_SYNC_INTERVAL_SECONDS=0)")
        return
    logger.info("ABox sync loop started (interval=%ss)", interval)
    while True:
        try:
            pool = get_api_pool()
            sparql: SparqlClient = app.state.sparql_client
            result = await sync_abox(pool, sparql, ABOX_GRAPH_URI)
            logger.info("ABox sync result: %s", result)
        except asyncio.CancelledError:
            logger.info("ABox sync loop cancelled")
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ABox sync iteration failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("ABox sync loop cancelled")
            raise


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- Startup ---
    logger.info("API starting up")
    await init_api_pool(settings.DATABASE_URL)

    app.state.temporal_client = await Client.connect(
        settings.TEMPORAL_HOST, namespace=settings.TEMPORAL_NAMESPACE
    )
    logger.info("Temporal client connected: %s", settings.TEMPORAL_HOST)

    app.state.sparql_client = SparqlClient(
        settings.FUSEKI_SPARQL_ENDPOINT, settings.FUSEKI_UPDATE_ENDPOINT
    )
    logger.info("SparqlClient created for %s", settings.FUSEKI_SPARQL_ENDPOINT)

    app.state.abox_task = asyncio.create_task(_abox_sync_loop(app))

    try:
        yield
    finally:
        # --- Shutdown ---
        logger.info("API shutting down")
        task: asyncio.Task | None = getattr(app.state, "abox_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        sparql: SparqlClient | None = getattr(app.state, "sparql_client", None)
        if sparql is not None:
            await sparql.aclose()
        await close_api_pool()
        # Temporal client needs no explicit close.
        logger.info("API shutdown complete")


app = FastAPI(
    title="Staffing System API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(persons.router)
app.include_router(projects.router)
app.include_router(teams.router)
app.include_router(opportunities.router)
app.include_router(assignments.router)
app.include_router(approvals.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Staffing System API", "version": "0.2.0", "docs": "/docs"}
