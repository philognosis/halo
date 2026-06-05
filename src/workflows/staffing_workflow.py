"""
TeamStaffingWorkflow — triggered by team_INSERT events.

Flow:
  1. Fetch team + open opportunities
  2. Mark domain event processed
  3. For each open opportunity:
     a. Fetch opportunity details (skills, band, region)
     b. SPARQL candidate search (with Postgres fallback)
     c. Compose and send candidate recommendation to leadership
  4. Wait up to 7 days for approve/reject signals
  5. For approved assignments: start AssignmentApprovalWorkflow as child
  6. Return summary

Signals:
  - approve_candidate(assignment_id, approver_id)
  - reject_candidate(assignment_id, reason)

Queries:
  - get_status() → current workflow state dict
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.activities.db_activities import (
        create_notifications_for_leadership,
        get_available_persons_by_region,
        get_opportunity_by_id,
        get_team_by_id,
        mark_domain_event_processed,
    )
    from src.activities.notification_activities import compose_candidate_recommendation
    from src.activities.sparql_activities import search_candidates
    from src.workflows.approval_workflow import AssignmentApprovalWorkflow

# ---------------------------------------------------------------------------
# Shared retry / timeout config
# ---------------------------------------------------------------------------
_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_SPARQL_TIMEOUT = timedelta(seconds=20)

# Signal wait timeout: 7 days
_SIGNAL_TIMEOUT = timedelta(days=7)


@workflow.defn(name="TeamStaffingWorkflow")
class TeamStaffingWorkflow:
    """
    Durable workflow that searches for candidates for every open opportunity
    in a newly created team, presents recommendations to leadership, then
    orchestrates HITL approval via child workflows.
    """

    def __init__(self) -> None:
        self._approved_assignments: list[dict[str, Any]] = []
        self._rejected_assignments: list[dict[str, Any]] = []
        self._pending_count: int = 0
        self._status: str = "initialising"

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    @workflow.signal
    async def approve_candidate(self, assignment_id: str, approver_id: str) -> None:
        workflow.logger.info(
            "approve_candidate signal: assignment_id=%s approver_id=%s",
            assignment_id,
            approver_id,
        )
        self._approved_assignments.append(
            {"assignment_id": assignment_id, "approver_id": approver_id}
        )
        if self._pending_count > 0:
            self._pending_count -= 1

    @workflow.signal
    async def reject_candidate(self, assignment_id: str, reason: str) -> None:
        workflow.logger.info(
            "reject_candidate signal: assignment_id=%s reason=%s", assignment_id, reason
        )
        self._rejected_assignments.append(
            {"assignment_id": assignment_id, "reason": reason}
        )
        if self._pending_count > 0:
            self._pending_count -= 1

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @workflow.query
    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "approved_count": len(self._approved_assignments),
            "rejected_count": len(self._rejected_assignments),
            "pending_count": self._pending_count,
            "approved_assignments": self._approved_assignments,
            "rejected_assignments": self._rejected_assignments,
        }

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------
    @workflow.run
    async def run(self, team_id: str, event_id: str) -> dict[str, Any]:
        workflow.logger.info(
            "TeamStaffingWorkflow started: team_id=%s event_id=%s", team_id, event_id
        )
        self._status = "fetching_team"

        # ------------------------------------------------------------------
        # Step 1: Fetch team + open opportunities
        # ------------------------------------------------------------------
        team: dict[str, Any] = await workflow.execute_activity(
            get_team_by_id,
            team_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        if not team:
            workflow.logger.warning(
                "TeamStaffingWorkflow: team %s not found — aborting", team_id
            )
            return {"status": "aborted", "reason": "team_not_found", "team_id": team_id}

        project_id: str = team.get("project_id", "")
        opportunities: list[dict[str, Any]] = team.get("opportunities", [])

        workflow.logger.info(
            "Team %s found: %s | Project: %s | Open opportunities: %d",
            team_id,
            team.get("name"),
            project_id,
            len(opportunities),
        )

        # ------------------------------------------------------------------
        # Step 2: Mark domain event processed
        # ------------------------------------------------------------------
        await workflow.execute_activity(
            mark_domain_event_processed,
            args=[event_id, None],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # ------------------------------------------------------------------
        # Step 3: Search candidates for each open opportunity
        # ------------------------------------------------------------------
        self._status = "searching_candidates"
        recommendation_notification_ids: list[str] = []
        opp_summaries: list[dict[str, Any]] = []

        for opp_stub in opportunities:
            opp_id = opp_stub.get("id", "")
            if not opp_id:
                continue

            # 3a. Fetch full opportunity details
            opportunity: dict[str, Any] = await workflow.execute_activity(
                get_opportunity_by_id,
                opp_id,
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            if not opportunity:
                continue

            required_skills = [s["skill_name"] for s in opportunity.get("required_skills", [])]
            required_band = opportunity.get("band_required", "Analyst")
            region = team.get("region")  # region from the joined project row

            # 3b. SPARQL candidate search
            candidates: list[dict[str, Any]] = await workflow.execute_activity(
                search_candidates,
                args=[opp_id, required_skills, required_band, region],
                start_to_close_timeout=_SPARQL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # 3c. Fallback to Postgres if SPARQL returns nothing
            if not candidates:
                workflow.logger.info(
                    "SPARQL returned no candidates for opp=%s — falling back to Postgres",
                    opp_id,
                )
                pg_persons: list[dict[str, Any]] = await workflow.execute_activity(
                    get_available_persons_by_region,
                    args=[region or "", required_band],
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY,
                )
                # Normalise Postgres rows to the candidate dict shape
                candidates = [
                    {
                        "person_uri": f"urn:person:{p.get('person_id', '')}",
                        "name": p.get("name", ""),
                        "band": p.get("band", ""),
                        "region": p.get("region", ""),
                        "availability_phase": p.get("availability_phase", ""),
                        "matched_skills": 0,
                        "score": 0,
                    }
                    for p in pg_persons
                ]

            # 3d. Compose candidate recommendation notification
            recommendation: dict[str, Any] = await workflow.execute_activity(
                compose_candidate_recommendation,
                args=[opportunity, candidates],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

            # 3e. Send notification to project leadership
            notif_ids: list[str] = await workflow.execute_activity(
                create_notifications_for_leadership,
                args=[
                    project_id,
                    event_id,
                    "candidate_recommendation",
                    recommendation["title"],
                    recommendation["body"],
                    recommendation["metadata"],
                ],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            recommendation_notification_ids.extend(notif_ids)
            workflow.logger.info(
                "Recommendation sent for opp=%s (%d candidates, %d notifications)",
                opp_id,
                len(candidates),
                len(notif_ids),
            )

            opp_summaries.append(
                {
                    "opportunity_id": opp_id,
                    "role_title": opportunity.get("role_title"),
                    "candidate_count": len(candidates),
                    "notification_ids": notif_ids,
                }
            )
            self._pending_count += 1

        # ------------------------------------------------------------------
        # Step 4: Wait for approve/reject signals (7-day window)
        # ------------------------------------------------------------------
        self._status = "awaiting_decisions"
        workflow.logger.info(
            "Waiting up to 7 days for approve/reject signals (pending=%d)",
            self._pending_count,
        )

        all_decided = await workflow.wait_condition(
            lambda: self._pending_count <= 0,
            timeout=_SIGNAL_TIMEOUT,
        )

        if not all_decided:
            workflow.logger.info(
                "Signal wait timed out after 7 days — proceeding with %d approvals, "
                "%d rejections, %d still pending",
                len(self._approved_assignments),
                len(self._rejected_assignments),
                self._pending_count,
            )

        # ------------------------------------------------------------------
        # Step 5: Start child AssignmentApprovalWorkflow for each approval
        # ------------------------------------------------------------------
        self._status = "processing_approvals"
        child_handles: list[Any] = []

        for approval in self._approved_assignments:
            assignment_id = approval["assignment_id"]
            child_wf_id = f"assignment-approval-{assignment_id}"

            workflow.logger.info(
                "Starting child AssignmentApprovalWorkflow for assignment=%s", assignment_id
            )
            handle = await workflow.start_child_workflow(
                AssignmentApprovalWorkflow,
                args=[assignment_id, event_id],
                id=child_wf_id,
                task_queue=workflow.info().task_queue,
            )
            child_handles.append(handle)

        # Fire-and-forget — approval workflows run independently
        workflow.logger.info(
            "Started %d child approval workflow(s)", len(child_handles)
        )

        self._status = "complete"
        return {
            "status": "complete",
            "team_id": team_id,
            "project_id": project_id,
            "opportunities_processed": len(opp_summaries),
            "opportunity_summaries": opp_summaries,
            "recommendation_notification_ids": recommendation_notification_ids,
            "approved_count": len(self._approved_assignments),
            "rejected_count": len(self._rejected_assignments),
        }
