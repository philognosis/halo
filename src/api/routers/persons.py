"""Person endpoints: listing, availability, full profile."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_pool

router = APIRouter(prefix="/persons", tags=["persons"])


@router.get("")
async def list_persons(
    region: str | None = Query(default=None),
    band: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    clauses: list[str] = []
    args: list[object] = []
    if region is not None:
        args.append(region)
        clauses.append(f"region = ${len(args)}")
    if band is not None:
        args.append(band)
        clauses.append(f"band = ${len(args)}")
    if status is not None:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    args.append(limit)
    limit_idx = len(args)
    args.append(offset)
    offset_idx = len(args)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id::TEXT, name, band, region, office, status
            FROM person
            {where}
            ORDER BY name
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *args,
        )
    return [dict(r) for r in rows]


@router.get("/{person_id}/availability")
async def person_availability(
    person_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                person_id::TEXT, name, band, region, office,
                person_status, allocated_pct, available_pct,
                active_assignment_count, availability_phase,
                next_available_date::TEXT,
                assignment_statuses,
                active_assignments
            FROM person_availability
            WHERE person_id = $1::UUID
            """,
            person_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="person not found")
    result = dict(row)
    # active_assignments is JSONB[]; asyncpg returns list of dicts/str
    result["active_assignments"] = [
        __import__("json").loads(a) if isinstance(a, str) else a
        for a in (result.get("active_assignments") or [])
    ]
    return result


@router.get("/{person_id}")
async def get_person(
    person_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        person = await conn.fetchrow(
            """
            SELECT
                id::TEXT, name, email, role, band, location, office, region,
                hire_date::TEXT, status, total_experience_months,
                experience_in_role_months
            FROM person
            WHERE id = $1::UUID
            """,
            person_id,
        )
        if person is None:
            raise HTTPException(status_code=404, detail="person not found")

        skills = await conn.fetch(
            """
            SELECT id::TEXT, skill_id, skill_name, skill_type,
                   proficiency_level, years_experience
            FROM skills WHERE person_id = $1::UUID ORDER BY skill_name
            """,
            person_id,
        )
        certs = await conn.fetch(
            """
            SELECT id::TEXT, name, issuer, issued_date::TEXT,
                   expiry_date::TEXT, is_valid
            FROM certifications WHERE person_id = $1::UUID ORDER BY name
            """,
            person_id,
        )
        quals = await conn.fetch(
            """
            SELECT id::TEXT, degree, institution, field_of_study,
                   graduation_year, level
            FROM qualifications WHERE person_id = $1::UUID
            """,
            person_id,
        )
        langs = await conn.fetch(
            """
            SELECT id::TEXT, language_code, language_name, proficiency
            FROM person_language WHERE person_id = $1::UUID
            """,
            person_id,
        )
        availability = await conn.fetchrow(
            """
            SELECT availability_phase, allocated_pct, available_pct,
                   active_assignment_count, next_available_date::TEXT
            FROM person_availability WHERE person_id = $1::UUID
            """,
            person_id,
        )

    result = dict(person)
    result["skills"] = [dict(r) for r in skills]
    result["certifications"] = [dict(r) for r in certs]
    result["qualifications"] = [dict(r) for r in quals]
    result["languages"] = [dict(r) for r in langs]
    result["availability"] = dict(availability) if availability else None
    return result
