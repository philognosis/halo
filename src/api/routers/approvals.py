"""
HITL signal relay — the heart of Phase 2.

The API process does NOT import the workflow classes (that would drag in the
Temporal sandbox). Instead it signals/queries workflows by STRING name via
``client.get_workflow_handle(workflow_id)``.

Workflow id conventions:
  - assignment-approval-{assignment_id}  → AssignmentApprovalWorkflow
  - team-staffing-{team_id}              → TeamStaffingWorkflow
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from temporalio.client import Client
from temporalio.service import RPCError

from src.api.dependencies import get_pool, get_temporal
from src.api.schemas import (
    ApproveRequest,
    CandidateApproveRequest,
    CandidateRejectRequest,
    RejectRequest,
    SignalResponse,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _not_found(workflow_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"approval workflow not found or already completed: {workflow_id}",
    )


# ---------------------------------------------------------------------------
# Assignment approval workflow (AssignmentApprovalWorkflow)
# ---------------------------------------------------------------------------
@router.post(
    "/assignments/{assignment_id}/approve", response_model=SignalResponse
)
async def approve_assignment(
    assignment_id: str,
    body: ApproveRequest,
    temporal: Client = Depends(get_temporal),
) -> SignalResponse:
    workflow_id = f"assignment-approval-{assignment_id}"
    handle = temporal.get_workflow_handle(workflow_id)
    try:
        await handle.signal("approve", args=[body.approver_id, body.notes])
    except RPCError:
        raise _not_found(workflow_id)
    return SignalResponse(signaled=True, workflow_id=workflow_id)


@router.post(
    "/assignments/{assignment_id}/reject", response_model=SignalResponse
)
async def reject_assignment(
    assignment_id: str,
    body: RejectRequest,
    temporal: Client = Depends(get_temporal),
) -> SignalResponse:
    workflow_id = f"assignment-approval-{assignment_id}"
    handle = temporal.get_workflow_handle(workflow_id)
    try:
        await handle.signal("reject", args=[body.approver_id, body.reason])
    except RPCError:
        raise _not_found(workflow_id)
    return SignalResponse(signaled=True, workflow_id=workflow_id)


@router.get("/assignments/{assignment_id}/status")
async def assignment_status(
    assignment_id: str,
    temporal: Client = Depends(get_temporal),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    workflow_id = f"assignment-approval-{assignment_id}"
    handle = temporal.get_workflow_handle(workflow_id)

    workflow_decision = None
    try:
        workflow_decision = await handle.query("get_decision")
    except RPCError:
        workflow_decision = None  # workflow may be gone; still report DB status

    async with pool.acquire() as conn:
        db_status = await conn.fetchval(
            "SELECT status FROM assignment WHERE id = $1::UUID", assignment_id
        )
    if db_status is None and workflow_decision is None:
        raise _not_found(workflow_id)

    return {
        "workflow_id": workflow_id,
        "workflow_decision": workflow_decision,
        "db_status": db_status,
    }


# ---------------------------------------------------------------------------
# Team staffing workflow (TeamStaffingWorkflow)
# ---------------------------------------------------------------------------
@router.post(
    "/teams/{team_id}/approve-candidate",
    response_model=SignalResponse,
)
async def approve_candidate(
    team_id: str,
    body: CandidateApproveRequest,
    temporal: Client = Depends(get_temporal),
) -> SignalResponse:
    workflow_id = f"team-staffing-{team_id}"
    handle = temporal.get_workflow_handle(workflow_id)
    try:
        await handle.signal(
            "approve_candidate",
            args=[
                body.opportunity_id,
                body.person_id,
                body.start_date,
                body.end_date,
                body.allocation_pct,
                body.approver_id,
            ],
        )
    except RPCError:
        raise _not_found(workflow_id)
    return SignalResponse(signaled=True, workflow_id=workflow_id)


@router.post(
    "/teams/{team_id}/reject-candidate",
    response_model=SignalResponse,
)
async def reject_candidate(
    team_id: str,
    body: CandidateRejectRequest,
    temporal: Client = Depends(get_temporal),
) -> SignalResponse:
    workflow_id = f"team-staffing-{team_id}"
    handle = temporal.get_workflow_handle(workflow_id)
    try:
        await handle.signal(
            "reject_candidate",
            args=[body.opportunity_id, body.person_id, body.reason],
        )
    except RPCError:
        raise _not_found(workflow_id)
    return SignalResponse(signaled=True, workflow_id=workflow_id)


@router.get("/teams/{team_id}/status")
async def team_status(
    team_id: str,
    temporal: Client = Depends(get_temporal),
) -> dict:
    workflow_id = f"team-staffing-{team_id}"
    handle = temporal.get_workflow_handle(workflow_id)
    try:
        status = await handle.query("get_status")
    except RPCError:
        raise _not_found(workflow_id)
    return {"workflow_id": workflow_id, "status": status}
