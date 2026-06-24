"""
Temporal activity wrappers for the agent layer (autonomous mode).

Each activity uses ``db_activities.get_pool()`` for the worker pool and a
module-level SparqlClient created lazily via ``init_agent_sparql()`` (called by
the worker at startup). All returns are JSON-serialisable: sets are converted to
lists, dates/Decimals are stringified/floated by the underlying queries, and we
defensively scrub any residual sets here.
"""
from __future__ import annotations

import logging
from typing import Any

from temporalio import activity

from src.activities.db_activities import get_pool
from src.agents.arbitration_graph import run_candidate_arbitration
from src.agents.conflict_resolution_graph import run_conflict_resolution
from src.agents.recommendation_graph import run_recommendation
from src.agents.team_composition_graph import run_team_composition_debate
from src.agents.team_shaping import propose_team_shape
from src.agents.tools import (
    compare_profiles,
    shortlist_candidate,
)
from src.bridge.sparql_client import SparqlClient
from src.config import settings

logger = logging.getLogger(__name__)

# Module-level SparqlClient — created by init_agent_sparql() at worker startup.
_sparql_client: SparqlClient | None = None


def init_agent_sparql() -> SparqlClient:
    """Create the module-level SparqlClient from settings (idempotent)."""
    global _sparql_client
    if _sparql_client is None:
        _sparql_client = SparqlClient(
            settings.FUSEKI_SPARQL_ENDPOINT, settings.FUSEKI_UPDATE_ENDPOINT
        )
        logger.info("Agent SparqlClient initialised for %s", settings.FUSEKI_SPARQL_ENDPOINT)
    return _sparql_client


def _get_sparql() -> SparqlClient | None:
    return _sparql_client


# ---------------------------------------------------------------------------
# JSON-serialisation scrubbing
# ---------------------------------------------------------------------------
def _json_safe(obj: Any) -> Any:
    """Recursively convert sets->lists and other non-JSON types to safe forms."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):  # date / datetime
        return obj.isoformat()
    # Decimal -> float
    try:
        from decimal import Decimal

        if isinstance(obj, Decimal):
            return float(obj)
    except Exception:  # pragma: no cover
        pass
    return obj


def _strip_candidate_internals(result: dict) -> dict:
    """Drop the heavy internal candidate dicts; ranked entries are already clean."""
    cleaned = dict(result)
    # 'requirement', 'ranked', 'top' are all serialisable; ranked entries carry
    # only scalar/list fields. Just scrub defensively.
    return _json_safe(cleaned)


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------
@activity.defn(name="agent_recommend_candidates")
async def agent_recommend_candidates(opportunity_id: str, top_n: int = 5) -> dict[str, Any]:
    activity.logger.info(
        "agent_recommend_candidates: opportunity_id=%s top_n=%s", opportunity_id, top_n
    )
    pool = get_pool()
    sparql = _get_sparql()
    result = await run_recommendation(
        pool,
        sparql,
        opportunity_id=opportunity_id,
        top_n=top_n,
        explain=settings.AGENT_EXPLAIN,
    )
    return _strip_candidate_internals(result)


@activity.defn(name="agent_propose_team_shape")
async def agent_propose_team_shape(project_id: str) -> dict[str, Any]:
    activity.logger.info("agent_propose_team_shape: project_id=%s", project_id)
    pool = get_pool()
    result = await propose_team_shape(pool, project_id, _get_sparql())
    return _json_safe(result)


@activity.defn(name="agent_shortlist_candidate")
async def agent_shortlist_candidate(
    opportunity_id: str,
    person_id: str,
    start_date: str,
    end_date: str | None,
    allocation_pct: float,
    assigned_by: str | None,
    notes: str,
) -> dict[str, Any]:
    activity.logger.info(
        "agent_shortlist_candidate: opportunity_id=%s person_id=%s",
        opportunity_id,
        person_id,
    )
    pool = get_pool()
    result = await shortlist_candidate(
        pool,
        opportunity_id,
        person_id,
        start_date,
        end_date,
        allocation_pct=allocation_pct,
        assigned_by=assigned_by,
        notes=notes or "",
    )
    return _json_safe(result)


@activity.defn(name="agent_compare_profiles")
async def agent_compare_profiles(
    person_ids: list, opportunity_id: str | None
) -> dict[str, Any]:
    activity.logger.info(
        "agent_compare_profiles: person_ids=%s opportunity_id=%s",
        person_ids,
        opportunity_id,
    )
    pool = get_pool()
    sparql = _get_sparql()
    result = await compare_profiles(pool, sparql, person_ids, opportunity_id)
    return _json_safe(result)


@activity.defn(name="agent_team_composition_debate")
async def agent_team_composition_debate(project_id: str) -> dict[str, Any]:
    activity.logger.info("agent_team_composition_debate: project_id=%s", project_id)
    pool = get_pool()
    result = await run_team_composition_debate(pool, project_id)
    return _json_safe(result)


@activity.defn(name="agent_candidate_arbitration")
async def agent_candidate_arbitration(
    opportunity_id: str,
    candidates: list,
    requirement: dict,
    top_n: int = 5,
) -> dict[str, Any]:
    activity.logger.info(
        "agent_candidate_arbitration: opportunity_id=%s candidates=%d",
        opportunity_id,
        len(candidates),
    )
    pool = get_pool()
    sparql = _get_sparql()
    result = await run_candidate_arbitration(
        pool, sparql, opportunity_id, candidates, requirement, top_n
    )
    return _json_safe(result)


@activity.defn(name="agent_conflict_resolution")
async def agent_conflict_resolution(
    assignment_details: dict,
    person: dict,
    opportunity: dict,
) -> dict[str, Any]:
    activity.logger.info(
        "agent_conflict_resolution: person=%s opportunity=%s",
        person.get("name", person.get("id")),
        opportunity.get("role_title", assignment_details.get("opportunity_id")),
    )
    pool = get_pool()
    result = await run_conflict_resolution(pool, assignment_details, person, opportunity)
    return _json_safe(result)
