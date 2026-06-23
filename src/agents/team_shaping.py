"""
Team-shaping proposal generator.

Given a project, produce a deterministic suggested team structure (roles, role
categories, bands, key skills) keyed off the project's function/industry. The
LLM may optionally refine titles/rationale text, but the roles and bands are
ALWAYS deterministic.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from src.config import settings

logger = logging.getLogger(__name__)


def _role(title: str, role_category: str, band: str, key_skills: list[str], rationale: str) -> dict:
    return {
        "role_title": title,
        "role_category": role_category,
        "band_required": band,
        "key_skills": key_skills,
        "rationale": rationale,
    }


# Deterministic templates keyed by a normalised function/industry token.
def _template_for(function: str, industry: str) -> list[dict]:
    f = (function or "").strip().lower()
    i = (industry or "").strip().lower()
    key = f or i

    if "tech" in key or "engineering" in key or "software" in key:
        return [
            _role("Solution Architect", "architect", "Manager",
                  ["architecture", "cloud", "system design"],
                  "Owns the technical solution and integration design."),
            _role("Senior Engineer", "engineer", "Consultant",
                  ["backend", "API", "testing"],
                  "Builds core services and reviews engineering quality."),
            _role("Engineer", "engineer", "Consultant",
                  ["backend", "frontend"],
                  "Delivers feature implementation across the stack."),
            _role("Business Analyst", "business_analyst", "Consultant",
                  ["requirements", "stakeholder management"],
                  "Translates client needs into technical requirements."),
            _role("Data Analyst", "analyst", "Analyst",
                  ["SQL", "reporting"],
                  "Provides delivery metrics and data-driven insight."),
        ]
    if "analytics" in key or "data" in key:
        return [
            _role("Data Lead", "lead", "Manager",
                  ["data strategy", "ML", "pipeline design"],
                  "Leads the analytics workstream and data architecture."),
            _role("Data Engineer", "engineer", "Consultant",
                  ["ETL", "Spark", "SQL"],
                  "Builds and maintains data pipelines."),
            _role("Data Engineer", "engineer", "Consultant",
                  ["ETL", "data modelling"],
                  "Supports pipeline build-out and data quality."),
            _role("Data Analyst", "analyst", "Analyst",
                  ["SQL", "visualisation", "reporting"],
                  "Produces analysis and dashboards for the client."),
        ]
    if "strategy" in key or "advisory" in key or "consult" in key:
        return [
            _role("Engagement Manager", "manager", "Manager",
                  ["engagement management", "client management"],
                  "Owns delivery and the client relationship."),
            _role("Consultant", "consultant", "Consultant",
                  ["problem solving", "analysis"],
                  "Drives core workstream analysis and synthesis."),
            _role("Consultant", "consultant", "Consultant",
                  ["research", "modelling"],
                  "Supports analysis and client deliverables."),
            _role("Business Analyst", "business_analyst", "Analyst",
                  ["data gathering", "modelling"],
                  "Handles data collection and quantitative support."),
        ]

    # Generic fallback — still 4 roles.
    return [
        _role("Engagement Manager", "manager", "Manager",
              ["delivery management", "client management"],
              "Leads delivery and manages the client relationship."),
        _role("Senior Consultant", "consultant", "Senior Consultant",
              ["analysis", "domain expertise"],
              "Owns a core workstream and mentors the team."),
        _role("Consultant", "consultant", "Consultant",
              ["analysis", "delivery"],
              "Delivers analysis and client work products."),
        _role("Analyst", "analyst", "Analyst",
              ["research", "data support"],
              "Provides research and quantitative support."),
    ]


async def propose_team_shape(
    pool: asyncpg.Pool, project_id: str, sparql_client: Any = None
) -> dict[str, Any]:
    """Return a suggested team structure for a project."""
    async with pool.acquire() as conn:
        project = await conn.fetchrow(
            """
            SELECT id::TEXT, project_name, client, industry, sector, function,
                   region, start_date::TEXT, end_date::TEXT, status
            FROM project WHERE id = $1::UUID
            """,
            project_id,
        )

    if project is None:
        return {}

    industry = project["industry"]
    function = project["function"]
    opportunities = _template_for(function, industry)

    if settings.ANTHROPIC_API_KEY:
        try:
            opportunities = await _llm_refine(project, opportunities)
        except Exception as exc:  # pragma: no cover - LLM failure
            logger.warning("LLM team-shape refinement failed: %s", exc)

    team_name = f"{project['project_name']} Delivery Team"
    return {
        "project_id": project["id"],
        "project_name": project["project_name"],
        "industry": industry,
        "function": function,
        "suggested_team": {
            "name": team_name,
            "opportunities": opportunities,
        },
    }


async def _llm_refine(project: Any, opportunities: list[dict]) -> list[dict]:
    """Refine titles/rationale via the LLM while keeping roles/bands fixed."""
    import json as _json

    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=1024,
        timeout=30,
    )

    system = (
        "You refine staffing role suggestions. You may improve role_title and "
        "rationale text for clarity and client-context fit, but you MUST keep "
        "each role's role_category and band_required EXACTLY as given, and keep "
        "the same number of roles. Return a JSON list of the refined roles."
    )
    user = (
        f"Project: {project['project_name']} for {project['client']}, "
        f"industry={project['industry']}, function={project['function']}.\n"
        f"Roles (do not change role_category or band_required):\n"
        + _json.dumps(opportunities)
        + "\n\nReturn only the JSON list."
    )

    resp = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        refined = _json.loads(text[start:end])
    except (ValueError, _json.JSONDecodeError):
        return opportunities

    if not isinstance(refined, list) or len(refined) != len(opportunities):
        return opportunities

    # Enforce that role_category and band_required were not altered.
    out: list[dict] = []
    for original, new in zip(opportunities, refined):
        out.append(
            {
                "role_title": new.get("role_title", original["role_title"]),
                "role_category": original["role_category"],
                "band_required": original["band_required"],
                "key_skills": new.get("key_skills", original["key_skills"]),
                "rationale": new.get("rationale", original["rationale"]),
            }
        )
    return out
