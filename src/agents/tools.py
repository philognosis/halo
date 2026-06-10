"""
Action tools used by both the conversational chat agent and the Temporal
activities. Each takes ``(pool, sparql_client, ...)`` as plain DI so it works in
either process context.

WRITE PATH: ``shortlist_candidate`` INSERTs an assignment with
status='short_listed'. The existing DB trigger + pg_listener then auto-start
AssignmentApprovalWorkflow exactly once. Do NOT start that workflow directly.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from src.agents.data_access import fetch_persons_by_ids, fetch_skos_skill_matches
from src.agents.recommendation_graph import run_recommendation
from src.agents.scoring import score_candidate
from src.agents.team_shaping import propose_team_shape
from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recommendation tools
# ---------------------------------------------------------------------------
async def recommend_for_opportunity(
    pool: asyncpg.Pool,
    sparql_client: Any,
    opportunity_id: str,
    top_n: int = 5,
    explain: bool = True,
) -> dict[str, Any]:
    """Recommend candidates for an existing opportunity."""
    return await run_recommendation(
        pool,
        sparql_client,
        opportunity_id=opportunity_id,
        top_n=top_n,
        explain=explain,
    )


async def recommend_for_spec(
    pool: asyncpg.Pool,
    sparql_client: Any,
    requirement: dict,
    top_n: int = 5,
    explain: bool = True,
) -> dict[str, Any]:
    """Recommend candidates for an ad-hoc requirement spec (from chat NL)."""
    return await run_recommendation(
        pool,
        sparql_client,
        requirement=requirement,
        top_n=top_n,
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Compare tool
# ---------------------------------------------------------------------------
async def compare_profiles(
    pool: asyncpg.Pool,
    sparql_client: Any,
    person_ids: list[str],
    opportunity_id: str | None,
) -> dict[str, Any]:
    """Compare profiles; if opportunity_id given, score each against it."""
    candidates = await fetch_persons_by_ids(pool, person_ids)

    requirement: dict | None = None
    if opportunity_id:
        from src.agents.data_access import fetch_requirement

        requirement = await fetch_requirement(pool, opportunity_id)

    # Resolve skill matches if we have a requirement to score against.
    if requirement:
        required_skill_ids = [
            s["skill_id"]
            for s in (requirement.get("mandatory_skills") or [])
            + (requirement.get("nice_skills") or [])
            if s.get("skill_id")
        ]
        sparql_matches: dict[str, set] = {}
        if required_skill_ids and sparql_client is not None:
            person_uris = [
                f"{settings.STF_NAMESPACE}person/{c['person_id']}" for c in candidates
            ]
            sparql_matches = await fetch_skos_skill_matches(
                sparql_client, settings.STF_NAMESPACE, person_uris, required_skill_ids
            )
        required_set = set(required_skill_ids)
        for c in candidates:
            direct = {
                s.get("skill_id")
                for s in (c.get("skills") or [])
                if s.get("skill_id") in required_set
            }
            c["matched_skill_ids"] = direct | sparql_matches.get(c["person_id"], set())

    profiles: list[dict] = []
    factor_matrix: dict[str, dict] = {}
    for c in candidates:
        base = {
            "person_id": c["person_id"],
            "name": c["name"],
            "band": c["band"],
            "region": c["region"],
            "role_category": c["role_category"],
            "skills": [s.get("skill_name") for s in (c.get("skills") or [])],
            "certifications": [
                cert.get("name") for cert in (c.get("certifications") or [])
            ],
            "languages": [l.get("language_code") for l in (c.get("languages") or [])],
            "total_experience_months": c.get("total_experience_months"),
        }
        if requirement:
            scored = score_candidate(c, requirement, weights={})
            base["overall_score"] = scored["overall_score"]
            base["gate_passed"] = scored["gate_passed"]
            base["factor_scores"] = scored["factor_scores"]
            base["matched_skills"] = scored["matched_skills"]
            factor_matrix[c["person_id"]] = scored["factor_scores"]
        profiles.append(base)

    result: dict[str, Any] = {"profiles": profiles, "factor_matrix": factor_matrix}
    if requirement:
        result["requirement"] = requirement
    return result


# ---------------------------------------------------------------------------
# Shortlist (WRITE path through trigger)
# ---------------------------------------------------------------------------
async def shortlist_candidate(
    pool: asyncpg.Pool,
    opportunity_id: str,
    person_id: str,
    start_date: str,
    end_date: str | None,
    allocation_pct: float = 100,
    assigned_by: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """
    INSERT an assignment (status='short_listed'). The DB trigger + pg_listener
    auto-start AssignmentApprovalWorkflow — do NOT start it directly here.
    """
    async with pool.acquire() as conn:
        assignment_id = await conn.fetchval(
            """
            INSERT INTO assignment
                (opportunity_id, person_id, start_date, end_date,
                 allocation_pct, status, notes, assigned_by)
            VALUES ($1::UUID, $2::UUID, $3::DATE, $4::DATE, $5, 'short_listed', $6, $7)
            RETURNING id::TEXT
            """,
            opportunity_id,
            person_id,
            start_date,
            end_date,
            allocation_pct,
            notes,
            assigned_by,
        )

    return {
        "assignment_id": assignment_id,
        "workflow_id": f"assignment-approval-{assignment_id}",
        "status": "short_listed",
    }


# ---------------------------------------------------------------------------
# Team-shape tool
# ---------------------------------------------------------------------------
async def propose_team(pool: asyncpg.Pool, project_id: str) -> dict[str, Any]:
    """Propose a team structure for a project."""
    return await propose_team_shape(pool, project_id)
