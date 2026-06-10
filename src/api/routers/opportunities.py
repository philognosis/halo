"""Opportunity endpoints, including ontology-aware candidate search."""
from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_pool, get_sparql
from src.api.schemas import (
    CandidateMatch,
    CandidateSearchResult,
    CreateOpportunityRequest,
    CreateOpportunityResponse,
)
from src.bridge.sparql_client import bands_gte, build_candidate_search
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.post("", status_code=201, response_model=CreateOpportunityResponse)
async def create_opportunity(
    body: CreateOpportunityRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> CreateOpportunityResponse:
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                opp_id = await conn.fetchval(
                    """
                    INSERT INTO opportunity
                        (team_id, role_title, description, band_required,
                         start_date, end_date, status)
                    VALUES ($1::UUID, $2, $3, $4, $5, $6, 'open')
                    RETURNING id::TEXT
                    """,
                    body.team_id,
                    body.role_title,
                    body.description,
                    body.band_required,
                    body.start_date,
                    body.end_date,
                )
            except asyncpg.ForeignKeyViolationError as exc:
                raise HTTPException(status_code=400, detail=f"invalid team_id: {exc}")
            except asyncpg.PostgresError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            for s in body.required_skills:
                await conn.execute(
                    """
                    INSERT INTO opportunity_skill
                        (opportunity_id, skill_id, skill_name, skill_type,
                         min_proficiency, is_mandatory)
                    VALUES ($1::UUID, $2, $3, $4, $5, $6)
                    """,
                    opp_id,
                    s.skill_id,
                    s.skill_name,
                    s.skill_type,
                    s.min_proficiency,
                    s.is_mandatory,
                )

            for q in body.required_qualifications:
                await conn.execute(
                    """
                    INSERT INTO opportunity_qualification
                        (opportunity_id, qualification_level, field_of_study, is_mandatory)
                    VALUES ($1::UUID, $2, $3, $4)
                    """,
                    opp_id,
                    q.qualification_level,
                    q.field_of_study,
                    q.is_mandatory,
                )

    return CreateOpportunityResponse(opportunity_id=opp_id)


@router.get("/{opportunity_id}")
async def get_opportunity(
    opportunity_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        opp = await conn.fetchrow(
            """
            SELECT o.id::TEXT, o.team_id::TEXT, o.role_title, o.description,
                   o.band_required, o.start_date::TEXT, o.end_date::TEXT,
                   o.status, o.notes, t.project_id::TEXT
            FROM opportunity o
            JOIN team t ON t.id = o.team_id
            WHERE o.id = $1::UUID
            """,
            opportunity_id,
        )
        if opp is None:
            raise HTTPException(status_code=404, detail="opportunity not found")

        skills = await conn.fetch(
            """
            SELECT id::TEXT, skill_id, skill_name, skill_type,
                   min_proficiency, is_mandatory
            FROM opportunity_skill WHERE opportunity_id = $1::UUID
            ORDER BY is_mandatory DESC, skill_name
            """,
            opportunity_id,
        )
        quals = await conn.fetch(
            """
            SELECT id::TEXT, qualification_level, field_of_study, is_mandatory
            FROM opportunity_qualification WHERE opportunity_id = $1::UUID
            """,
            opportunity_id,
        )

    result = dict(opp)
    result["required_skills"] = [dict(r) for r in skills]
    result["required_qualifications"] = [dict(r) for r in quals]
    return result


async def _fetch_opp_search_context(
    conn: asyncpg.Connection, opportunity_id: str
) -> dict:
    """Return required skills, band, and the project region for an opportunity."""
    opp = await conn.fetchrow(
        """
        SELECT o.id::TEXT, o.band_required, t.project_id::TEXT
        FROM opportunity o
        JOIN team t ON t.id = o.team_id
        WHERE o.id = $1::UUID
        """,
        opportunity_id,
    )
    if opp is None:
        return {}

    skill_rows = await conn.fetch(
        """
        SELECT COALESCE(skill_id, skill_name) AS skill_key
        FROM opportunity_skill WHERE opportunity_id = $1::UUID
        """,
        opportunity_id,
    )
    required_skills = [r["skill_key"] for r in skill_rows if r["skill_key"]]

    # The project table has no region column; derive region from the most
    # common region of project leadership (best-effort), else None.
    region = await conn.fetchval(
        """
        SELECT per.region
        FROM leadership l
        JOIN person per ON per.id = l.person_id
        WHERE l.project_id = $1::UUID
        GROUP BY per.region
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        opp["project_id"],
    )
    return {
        "band_required": opp["band_required"],
        "required_skills": required_skills,
        "region": region,
    }


@router.get("/{opportunity_id}/candidates", response_model=CandidateSearchResult)
async def get_candidates(
    opportunity_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    sparql=Depends(get_sparql),
) -> CandidateSearchResult:
    async with pool.acquire() as conn:
        ctx = await _fetch_opp_search_context(conn, opportunity_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="opportunity not found")

        required_band = ctx["band_required"]
        required_skills = ctx["required_skills"]
        region = ctx["region"]

        # --- Try Jena first ---
        candidates: list[CandidateMatch] = []
        source = "jena"
        try:
            query = build_candidate_search(
                settings.STF_NAMESPACE, required_skills, required_band, region
            )
            rows = await sparql.select(query)
            for r in rows:
                person_uri = r.get("person", "")
                person_id = person_uri.rsplit("/", 1)[-1] if person_uri else None
                band = r.get("band", "")
                phase = r.get("availabilityPhase", "")
                if isinstance(phase, str):
                    phase = phase.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                matched = int(r.get("matched_skills", 0) or 0)
                candidates.append(
                    CandidateMatch(
                        person_uri=person_uri,
                        person_id=person_id,
                        name=r.get("name", ""),
                        band=band,
                        region=r.get("region", ""),
                        availability_phase=phase,
                        matched_skills=matched,
                        score=matched,
                    )
                )
        except Exception as exc:
            logger.warning("Jena candidate search failed for %s: %s", opportunity_id, exc)
            candidates = []

        # --- Postgres fallback ---
        if not candidates:
            source = "postgres_fallback"
            eligible_bands = bands_gte(required_band)
            pg_args: list[object] = [eligible_bands]
            region_clause = ""
            if region:
                pg_args.append(region)
                region_clause = f"AND pa.region = ${len(pg_args)}"
            rows = await conn.fetch(
                f"""
                SELECT pa.person_id::TEXT, pa.name, pa.band, pa.region,
                       pa.availability_phase
                FROM person_availability pa
                WHERE pa.band = ANY($1::TEXT[])
                  {region_clause}
                  AND pa.person_status IN ('active', 'bench')
                  AND pa.availability_phase != 'FullyAllocated'
                ORDER BY pa.available_pct DESC, pa.band
                LIMIT 25
                """,
                *pg_args,
            )
            for r in rows:
                candidates.append(
                    CandidateMatch(
                        person_uri=f"{settings.STF_NAMESPACE}person/{r['person_id']}",
                        person_id=r["person_id"],
                        name=r["name"],
                        band=r["band"],
                        region=r["region"],
                        availability_phase=r["availability_phase"],
                        matched_skills=0,
                        score=0,
                    )
                )

    return CandidateSearchResult(
        opportunity_id=opportunity_id,
        source=source,
        count=len(candidates),
        candidates=candidates,
    )
