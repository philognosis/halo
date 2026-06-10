"""
FastAPI dependency providers.

The Temporal client and SparqlClient are created once in the app lifespan and
stored on ``app.state``. These providers expose them (and the API pool) to
endpoint handlers via ``Depends``.
"""
from __future__ import annotations

import asyncpg
from fastapi import Request
from temporalio.client import Client

from src.api.db import get_api_pool
from src.bridge.sparql_client import SparqlClient


def get_pool() -> asyncpg.Pool:
    """Return the API-local asyncpg pool."""
    return get_api_pool()


def get_temporal(request: Request) -> Client:
    """Return the Temporal client stored on app.state during lifespan startup."""
    client: Client | None = getattr(request.app.state, "temporal_client", None)
    if client is None:
        raise RuntimeError("Temporal client is not initialised on app.state.")
    return client


def get_sparql(request: Request) -> SparqlClient:
    """Return the SparqlClient stored on app.state during lifespan startup."""
    client: SparqlClient | None = getattr(request.app.state, "sparql_client", None)
    if client is None:
        raise RuntimeError("SparqlClient is not initialised on app.state.")
    return client
