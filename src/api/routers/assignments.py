"""
Assignment (shortlist) endpoints.

POST /assignments ONLY inserts the row with status='short_listed'. The DB
trigger fires pg_notify → pg_listener auto-starts AssignmentApprovalWorkflow.
This endpoint must NEVER talk to Temporal directly.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_pool
from src.api.schemas import CreateShortlistRequest, CreateShortlistResponse

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("", status_code=201, response_model=CreateShortlistResponse)
async def create_shortlist(
    body: CreateShortlistRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> CreateShortlistResponse:
    async with pool.acquire() as conn:
        try:
            assignment_id = await conn.fetchval(
                """
                INSERT INTO assignment
                    (opportunity_id, person_id, start_date, end_date,
                     allocation_pct, status, notes, assigned_by)
                VALUES ($1::UUID, $2::UUID, $3, $4, $5, 'short_listed', $6, $7::UUID)
                RETURNING id::TEXT
                """,
                body.opportunity_id,
                body.person_id,
                body.start_date,
                body.end_date,
                body.allocation_pct,
                body.notes,
                body.assigned_by,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid opportunity_id or person_id: {exc}"
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409, detail=f"duplicate active assignment: {exc}"
            )
        except asyncpg.RaiseError as exc:
            # Triggers fn_block_unavailable_assignment / fn_check_allocation_cap
            raise HTTPException(status_code=409, detail=str(exc))
        except asyncpg.PostgresError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return CreateShortlistResponse(
        assignment_id=assignment_id,
        workflow_id=f"assignment-approval-{assignment_id}",
        status="short_listed",
    )


@router.get("")
async def list_assignments(
    person_id: str | None = Query(default=None),
    opportunity_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    clauses: list[str] = []
    args: list[object] = []
    if person_id is not None:
        args.append(person_id)
        clauses.append(f"a.person_id = ${len(args)}::UUID")
    if opportunity_id is not None:
        args.append(opportunity_id)
        clauses.append(f"a.opportunity_id = ${len(args)}::UUID")
    if status is not None:
        args.append(status)
        clauses.append(f"a.status = ${len(args)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    args.append(limit)
    limit_idx = len(args)
    args.append(offset)
    offset_idx = len(args)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT a.id::TEXT, a.opportunity_id::TEXT, a.person_id::TEXT,
                   a.start_date::TEXT, a.end_date::TEXT, a.allocation_pct,
                   a.status, a.notes, a.assigned_at::TEXT
            FROM assignment a
            {where}
            ORDER BY a.assigned_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *args,
        )
    return [dict(r) for r in rows]


@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.id::TEXT, a.opportunity_id::TEXT, a.person_id::TEXT,
                a.start_date::TEXT, a.end_date::TEXT,
                a.allocation_pct, a.status, a.notes,
                a.assigned_by::TEXT, a.assigned_at::TEXT,
                p.name AS person_name, p.email AS person_email,
                p.band AS person_band, p.region AS person_region,
                p.office AS person_office, p.status AS person_status,
                o.role_title, o.band_required,
                o.start_date::TEXT AS opp_start_date,
                o.end_date::TEXT   AS opp_end_date,
                o.description      AS opp_description,
                t.project_id::TEXT
            FROM assignment a
            JOIN person p      ON p.id = a.person_id
            JOIN opportunity o ON o.id = a.opportunity_id
            JOIN team t        ON t.id = o.team_id
            WHERE a.id = $1::UUID
            """,
            assignment_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="assignment not found")
    return dict(row)
