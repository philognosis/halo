"""
Conversational + agent-action endpoints.

These run synchronously in the API process using the API-local pool and the
SparqlClient stored on ``app.state.sparql_client``. The chat endpoint is the
only natural-language entry point; the /agents/* endpoints are direct
read/action tools.
"""
from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.agents.chat_graph import run_chat
from src.agents.tools import (
    compare_profiles,
    propose_team,
    recommend_for_opportunity,
)
from src.api.dependencies import get_pool, get_sparql
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChatContext(BaseModel):
    project_id: str | None = None
    opportunity_id: str | None = None
    person_id: str | None = None


class ChatRequest(BaseModel):
    message: str
    context: ChatContext | None = None


class CompareRequest(BaseModel):
    person_ids: list[str]
    opportunity_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/chat")
async def chat(
    body: ChatRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    sparql=Depends(get_sparql),
) -> dict:
    context = body.context.model_dump() if body.context else {}
    result = await run_chat(pool, sparql, body.message, context)
    return result


@router.post("/agents/recommend/{opportunity_id}")
async def agents_recommend(
    opportunity_id: str,
    top_n: int = settings.RECOMMENDATION_TOP_N,
    explain: bool = True,
    pool: asyncpg.Pool = Depends(get_pool),
    sparql=Depends(get_sparql),
) -> dict:
    return await recommend_for_opportunity(
        pool, sparql, opportunity_id, top_n=top_n, explain=explain
    )


@router.post("/agents/compare")
async def agents_compare(
    body: CompareRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    sparql=Depends(get_sparql),
) -> dict:
    return await compare_profiles(pool, sparql, body.person_ids, body.opportunity_id)


@router.post("/agents/team-shape/{project_id}")
async def agents_team_shape(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    return await propose_team(pool, project_id)
