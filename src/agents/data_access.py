"""
Async data fetchers for the recommendation agent.

These functions take an asyncpg pool (worker pool OR api pool — pure DI) and/or
a SparqlClient and assemble the plain dicts that ``scoring.py`` consumes. They
perform all the I/O; the scorer stays pure.

All Postgres queries are parameterised. SPARQL skill resolution is best-effort:
``fetch_skos_skill_matches`` returns ``{}`` on any failure so the caller can
fall back to direct Postgres skill_id matching.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from src.bridge.sparql_client import SKOS, XSD, _escape_iri

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Requirement assembly
# ---------------------------------------------------------------------------
async def fetch_requirement(pool: asyncpg.Pool, opportunity_id: str) -> dict[str, Any]:
    """
    Assemble the requirement dict for an opportunity from Postgres.

    Pulls opportunity row + role_category + band_required, the parent project
    (industry, function, region), and the requirement child tables (skills,
    certs, quals, languages, citizenships).
    """
    async with pool.acquire() as conn:
        opp = await conn.fetchrow(
            """
            SELECT o.id::TEXT, o.role_title, o.role_category, o.band_required,
                   o.start_date::TEXT, o.end_date::TEXT, o.status,
                   t.project_id::TEXT,
                   p.industry, p.function, p.region, p.sector
            FROM opportunity o
            JOIN team t    ON t.id = o.team_id
            JOIN project p ON p.id = t.project_id
            WHERE o.id = $1::UUID
            """,
            opportunity_id,
        )
        if opp is None:
            return {}

        skills = await conn.fetch(
            """
            SELECT skill_id, skill_name, skill_type, min_proficiency, is_mandatory
            FROM opportunity_skill WHERE opportunity_id = $1::UUID
            """,
            opportunity_id,
        )
        certs = await conn.fetch(
            "SELECT cert_name, is_mandatory FROM opportunity_certification WHERE opportunity_id = $1::UUID",
            opportunity_id,
        )
        quals = await conn.fetch(
            """
            SELECT qualification_level, field_of_study, is_mandatory
            FROM opportunity_qualification WHERE opportunity_id = $1::UUID
            """,
            opportunity_id,
        )
        langs = await conn.fetch(
            """
            SELECT language_code, min_proficiency, is_mandatory
            FROM opportunity_language WHERE opportunity_id = $1::UUID
            """,
            opportunity_id,
        )
        cits = await conn.fetch(
            "SELECT country_code, is_mandatory FROM opportunity_citizenship WHERE opportunity_id = $1::UUID",
            opportunity_id,
        )

    mandatory_skills = [
        {"skill_id": s["skill_id"] or s["skill_name"], "name": s["skill_name"]}
        for s in skills
        if s["is_mandatory"]
    ]
    nice_skills = [
        {"skill_id": s["skill_id"] or s["skill_name"], "name": s["skill_name"]}
        for s in skills
        if not s["is_mandatory"]
    ]

    return {
        "opportunity_id": opp["id"],
        "role_title": opp["role_title"],
        "role_category": opp["role_category"],
        "band_required": opp["band_required"],
        "project_id": opp["project_id"],
        "industry": opp["industry"],
        "function": opp["function"],
        "sector": opp["sector"],
        "region": opp["region"],
        "office": None,
        "mandatory_skills": mandatory_skills,
        "nice_skills": nice_skills,
        "mandatory_certs": [c["cert_name"] for c in certs if c["is_mandatory"]],
        "nice_certs": [c["cert_name"] for c in certs if not c["is_mandatory"]],
        "mandatory_quals": [
            {"level": q["qualification_level"], "field": q["field_of_study"]}
            for q in quals
            if q["is_mandatory"]
        ],
        "nice_quals": [
            {"level": q["qualification_level"], "field": q["field_of_study"]}
            for q in quals
            if not q["is_mandatory"]
        ],
        "mandatory_languages": [
            {"code": l["language_code"], "min_prof": l["min_proficiency"]}
            for l in langs
            if l["is_mandatory"]
        ],
        "nice_languages": [
            {"code": l["language_code"], "min_prof": l["min_proficiency"]}
            for l in langs
            if not l["is_mandatory"]
        ],
        "mandatory_citizenships": [c["country_code"] for c in cits if c["is_mandatory"]],
        "nice_citizenships": [c["country_code"] for c in cits if not c["is_mandatory"]],
        "requested_allocation_pct": 100,
    }


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------
async def fetch_candidate_pool(
    pool: asyncpg.Pool, region: str | None, band_required: str
) -> list[dict[str, Any]]:
    """
    Return base candidate dicts: persons in (active, bench) with band rank >=
    required, optional region filter, joined with person_availability.
    """
    from src.agents.scoring import BAND_HIERARCHY

    try:
        idx = BAND_HIERARCHY.index(band_required)
    except (ValueError, TypeError):
        idx = 0
    eligible_bands = BAND_HIERARCHY[idx:]

    args: list[Any] = [eligible_bands]
    region_clause = ""
    if region:
        args.append(region)
        region_clause = f"AND p.region = ${len(args)}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                p.id::TEXT             AS person_id,
                p.name, p.band, p.region, p.office, p.role_category,
                p.status,
                p.total_experience_months,
                p.experience_in_role_months,
                pa.availability_phase,
                COALESCE(pa.available_pct, 100)  AS available_pct,
                COALESCE(pa.allocated_pct, 0)    AS allocated_pct
            FROM person p
            LEFT JOIN person_availability pa ON pa.person_id = p.id
            WHERE p.band = ANY($1::TEXT[])
              AND p.status IN ('active', 'bench')
              {region_clause}
            ORDER BY p.band DESC
            LIMIT 200
            """,
            *args,
        )

    candidates: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["available_pct"] = float(d["available_pct"])
        d["allocated_pct"] = float(d["allocated_pct"])
        d["total_experience_months"] = int(d["total_experience_months"] or 0)
        d["experience_in_role_months"] = int(d["experience_in_role_months"] or 0)
        # Placeholders populated by enrich_candidates.
        d["skills"] = []
        d["certifications"] = []
        d["qualifications"] = []
        d["languages"] = []
        d["citizenships"] = []
        d["industry_exposure"] = []
        d["domain_skills"] = []
        d["matched_skill_ids"] = set()
        candidates.append(d)
    return candidates


# ---------------------------------------------------------------------------
# Bulk enrichment
# ---------------------------------------------------------------------------
async def enrich_candidates(pool: asyncpg.Pool, candidates: list[dict]) -> None:
    """Bulk-load skills/certs/quals/languages/citizenships/industry exposure."""
    if not candidates:
        return
    ids = [c["person_id"] for c in candidates]
    by_id = {c["person_id"]: c for c in candidates}

    async with pool.acquire() as conn:
        skills = await conn.fetch(
            """
            SELECT person_id::TEXT, skill_id, skill_name, skill_type,
                   proficiency_level, years_experience
            FROM skills WHERE person_id = ANY($1::UUID[])
            """,
            ids,
        )
        certs = await conn.fetch(
            """
            SELECT person_id::TEXT, name, is_valid, expiry_date::TEXT
            FROM certifications WHERE person_id = ANY($1::UUID[])
            """,
            ids,
        )
        quals = await conn.fetch(
            """
            SELECT person_id::TEXT, level, field_of_study
            FROM qualifications WHERE person_id = ANY($1::UUID[])
            """,
            ids,
        )
        langs = await conn.fetch(
            """
            SELECT person_id::TEXT, language_code, proficiency
            FROM person_language WHERE person_id = ANY($1::UUID[])
            """,
            ids,
        )
        cits = await conn.fetch(
            "SELECT person_id::TEXT, country_code FROM person_citizenship WHERE person_id = ANY($1::UUID[])",
            ids,
        )
        exposure = await conn.fetch(
            """
            SELECT DISTINCT sh.person_id::TEXT, pr.industry
            FROM staffing_history sh
            JOIN project pr ON pr.id = sh.project_id
            WHERE sh.person_id = ANY($1::UUID[])
            """,
            ids,
        )

    for s in skills:
        c = by_id.get(s["person_id"])
        if c is None:
            continue
        c["skills"].append(
            {
                "skill_id": s["skill_id"],
                "skill_name": s["skill_name"],
                "skill_type": s["skill_type"],
                "proficiency_level": s["proficiency_level"],
                "years_experience": float(s["years_experience"])
                if s["years_experience"] is not None
                else None,
            }
        )
        if s["skill_type"] == "domain":
            c["domain_skills"].append(s["skill_name"])

    for ct in certs:
        c = by_id.get(ct["person_id"])
        if c is not None:
            c["certifications"].append(
                {
                    "name": ct["name"],
                    "is_valid": bool(ct["is_valid"]),
                    "expiry_date": ct["expiry_date"],
                }
            )

    for q in quals:
        c = by_id.get(q["person_id"])
        if c is not None:
            c["qualifications"].append(
                {"level": q["level"], "field_of_study": q["field_of_study"]}
            )

    for l in langs:
        c = by_id.get(l["person_id"])
        if c is not None:
            c["languages"].append(
                {"language_code": l["language_code"], "proficiency": l["proficiency"]}
            )

    for ci in cits:
        c = by_id.get(ci["person_id"])
        if c is not None:
            c["citizenships"].append(ci["country_code"])

    for ex in exposure:
        c = by_id.get(ex["person_id"])
        if c is not None and ex["industry"]:
            c["industry_exposure"].append(ex["industry"])


# ---------------------------------------------------------------------------
# SPARQL (SKOS-transitive) skill matching
# ---------------------------------------------------------------------------
async def fetch_skos_skill_matches(
    sparql_client: Any,
    stf_ns: str,
    person_uris: list[str],
    required_skill_ids: list[str],
) -> dict[str, set]:
    """
    For each person URI, return the set of required skill_ids they satisfy
    directly OR via ``skos:broaderTransitive*`` (a more-specific owned skill
    satisfies a broader requirement).

    Returns ``{person_id: set(matched_skill_ids)}``. On any error/empty input
    returns ``{}`` so the caller falls back to direct Postgres matching.
    """
    if sparql_client is None or not person_uris or not required_skill_ids:
        return {}

    person_values = " ".join(f"<{_escape_iri(u)}>" for u in person_uris)
    # Each required skill is represented as a concept URI (stf_ns + notation).
    # We match an employee's owned skill concept that is the required concept or
    # narrower (skos:broaderTransitive* from owned -> required).
    skill_values = " ".join(
        f"<{_escape_iri(stf_ns + str(sid).replace(' ', '_'))}>"
        for sid in required_skill_ids
    )
    # Map the required concept URI back to the skill_id via notation.
    id_by_uri = {
        stf_ns + str(sid).replace(" ", "_"): str(sid) for sid in required_skill_ids
    }

    query = f"""
    PREFIX stf:  <{stf_ns}>
    PREFIX skos: <{SKOS}>
    PREFIX xsd:  <{XSD}>

    SELECT DISTINCT ?person ?reqSkill
    WHERE {{
      VALUES ?person   {{ {person_values} }}
      VALUES ?reqSkill {{ {skill_values} }}
      ?person stf:hasSkill ?owned .
      ?owned skos:broaderTransitive* ?reqSkill .
    }}
    """

    try:
        rows = await sparql_client.select(query)
    except Exception as exc:  # pragma: no cover - network/SPARQL failure
        logger.warning("SKOS skill match query failed: %s", exc)
        return {}

    result: dict[str, set] = {}
    for r in rows:
        person_uri = r.get("person", "")
        req_uri = r.get("reqSkill", "")
        person_id = person_uri.rsplit("/", 1)[-1] if person_uri else None
        sid = id_by_uri.get(req_uri)
        if person_id and sid is not None:
            result.setdefault(person_id, set()).add(sid)
    return result


# ---------------------------------------------------------------------------
# Persons by id (for compare)
# ---------------------------------------------------------------------------
async def fetch_persons_by_ids(
    pool: asyncpg.Pool, person_ids: list[str]
) -> list[dict[str, Any]]:
    """Return full base candidate rows (enriched) for the given person ids."""
    if not person_ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.id::TEXT AS person_id,
                p.name, p.band, p.region, p.office, p.role_category, p.status,
                p.total_experience_months, p.experience_in_role_months,
                pa.availability_phase,
                COALESCE(pa.available_pct, 100) AS available_pct,
                COALESCE(pa.allocated_pct, 0)   AS allocated_pct
            FROM person p
            LEFT JOIN person_availability pa ON pa.person_id = p.id
            WHERE p.id = ANY($1::UUID[])
            """,
            person_ids,
        )

    candidates: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["available_pct"] = float(d["available_pct"])
        d["allocated_pct"] = float(d["allocated_pct"])
        d["total_experience_months"] = int(d["total_experience_months"] or 0)
        d["experience_in_role_months"] = int(d["experience_in_role_months"] or 0)
        d["skills"] = []
        d["certifications"] = []
        d["qualifications"] = []
        d["languages"] = []
        d["citizenships"] = []
        d["industry_exposure"] = []
        d["domain_skills"] = []
        d["matched_skill_ids"] = set()
        candidates.append(d)

    await enrich_candidates(pool, candidates)
    return candidates
