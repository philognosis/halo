"""Project endpoints. Creating a project auto-fires ProjectOnboardingWorkflow."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_pool
from src.api.schemas import CreateProjectRequest, CreateProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    status: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    clauses: list[str] = []
    args: list[object] = []
    if status is not None:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if industry is not None:
        args.append(industry)
        clauses.append(f"industry = ${len(args)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    args.append(limit)
    limit_idx = len(args)
    args.append(offset)
    offset_idx = len(args)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id::TEXT, unique_code, client, project_name,
                   start_date::TEXT, end_date::TEXT,
                   industry, sector, function, status
            FROM project
            {where}
            ORDER BY created_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *args,
        )
    return [dict(r) for r in rows]


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        project = await conn.fetchrow(
            """
            SELECT id::TEXT, unique_code, client, project_name,
                   start_date::TEXT, end_date::TEXT,
                   industry, sector, function, status,
                   created_at::TEXT, updated_at::TEXT
            FROM project WHERE id = $1::UUID
            """,
            project_id,
        )
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        leadership = await conn.fetch(
            """
            SELECT l.id::TEXT, l.role, l.person_id::TEXT,
                   per.name AS person_name, per.email AS person_email
            FROM leadership l
            JOIN person per ON per.id = l.person_id
            WHERE l.project_id = $1::UUID ORDER BY l.role
            """,
            project_id,
        )
        teams = await conn.fetch(
            """
            SELECT id::TEXT, name, team_lead_id::TEXT, created_at::TEXT
            FROM team WHERE project_id = $1::UUID ORDER BY created_at
            """,
            project_id,
        )

    result = dict(project)
    result["leadership"] = [dict(r) for r in leadership]
    result["teams"] = [dict(r) for r in teams]
    return result


@router.post("", status_code=201, response_model=CreateProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> CreateProjectResponse:
    async with pool.acquire() as conn:
        try:
            project_id = await conn.fetchval(
                """
                INSERT INTO project
                    (unique_code, client, project_name, start_date, end_date,
                     industry, sector, function, region, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id::TEXT
                """,
                body.unique_code,
                body.client,
                body.project_name,
                body.start_date,
                body.end_date,
                body.industry,
                body.sector,
                body.function,
                body.region,
                body.status,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=409, detail=f"project unique_code already exists: {exc}"
            )
        except asyncpg.PostgresError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return CreateProjectResponse(
        project_id=project_id, workflow_id=f"project-onboarding-{project_id}"
    )
