"""Team endpoints. Creating a team auto-fires TeamStaffingWorkflow."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_pool
from src.api.schemas import CreateTeamRequest, CreateTeamResponse

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", status_code=201, response_model=CreateTeamResponse)
async def create_team(
    body: CreateTeamRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> CreateTeamResponse:
    async with pool.acquire() as conn:
        try:
            team_id = await conn.fetchval(
                """
                INSERT INTO team (project_id, name, team_lead_id)
                VALUES ($1::UUID, $2, $3::UUID)
                RETURNING id::TEXT
                """,
                body.project_id,
                body.name,
                body.team_lead_id,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid project_id or team_lead_id: {exc}"
            )
        except asyncpg.PostgresError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return CreateTeamResponse(
        team_id=team_id, workflow_id=f"team-staffing-{team_id}"
    )


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        team = await conn.fetchrow(
            """
            SELECT t.id::TEXT, t.name, t.project_id::TEXT, t.team_lead_id::TEXT,
                   t.created_at::TEXT,
                   p.project_name, p.client, p.status AS project_status
            FROM team t
            JOIN project p ON p.id = t.project_id
            WHERE t.id = $1::UUID
            """,
            team_id,
        )
        if team is None:
            raise HTTPException(status_code=404, detail="team not found")

        opps = await conn.fetch(
            """
            SELECT id::TEXT, role_title, description, band_required,
                   start_date::TEXT, end_date::TEXT, status, notes
            FROM opportunity WHERE team_id = $1::UUID ORDER BY created_at
            """,
            team_id,
        )

    result = dict(team)
    result["opportunities"] = [dict(r) for r in opps]
    return result
