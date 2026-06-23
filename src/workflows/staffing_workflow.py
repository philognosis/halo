"""
TeamStaffingWorkflow — triggered by team_INSERT events.

Flow:
  1. Fetch team + open opportunities
  2. Mark domain event processed
  3. For each open opportunity:
     a. Run the agent recommender (agent_recommend_candidates) — deterministic,
        auditable scoring. Postgres fallback only if the agent returns nothing.
     b. Compose and send candidate recommendation to leadership (with scores).
        Store recommended-candidate context keyed by opportunity_id so an
        approval signal can shortlist with full info.
  4. Wait up to 7 days for approve/reject signals
  5. For each approval: call agent_shortlist_candidate to INSERT the assignment.
     The DB trigger + pg_listener then start AssignmentApprovalWorkflow EXACTLY
     ONCE (reconciliation fix #2 — we no longer start the child workflow here,
     which previously double-started it).
  6. Return summary

Signals:
  - approve_candidate(opportunity_id, person_id, start_date, end_date,
                      allocation_pct, approver_id)
      Carries everything needed to shortlist the chosen candidate. (Changed from
      the old assignment_id-based signature, which assumed an assignment already
      existed — it did not, so the old child-workflow start was a no-op/duplicate
      hazard.)
  - reject_candidate(opportunity_id, person_id, reason)

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
    from src.agents.activities import (
        agent_recommend_candidates,
        agent_shortlist_candidate,
    )

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
_AGENT_TIMEOUT = timedelta(seconds=60)

# Signal wait timeout: 7 days
_SIGNAL_TIMEOUT = timedelta(days=7)


@workflow.defn(name="TeamStaffingWorkflow")
class TeamStaffingWorkflow:
    """
    Durable workflow that recommends candidates for every open opportunity in a
    newly created team, presents recommendations to leadership, then — on human
    approval — shortlists the chosen candidate (which fires the DB trigger that
    starts AssignmentApprovalWorkflow exactly once).
    """

    def __init__(self) -> None:
        self._approved: list[dict[str, Any]] = []
        self._rejected: list[dict[str, Any]] = []
        self._shortlisted: list[dict[str, Any]] = []
        self._pending_count: int = 0
        self._status: str = "initialising"
        # Recommendation context per opportunity (defaults for shortlisting).
        self._opp_context: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    @workflow.signal
    async def approve_candidate(
        self,
        opportunity_id: str,
        person_id: str,
        start_date: str = "",
        end_date: str = "",
        allocation_pct: float = 100,
        approver_id: str = "",
    ) -> None:
        """Approve a recommended candidate for an opportunity.

        Carries enough info to shortlist directly. Dates fall back to the
        opportunity's own dates (captured in recommendation context) when blank.
        """
        workflow.logger.info(
            "approve_candidate signal: opportunity_id=%s person_id=%s approver_id=%s",
            opportunity_id,
            person_id,
            approver_id,
        )
        self._approved.append(
            {
                "opportunity_id": opportunity_id,
                "person_id": person_id,
                "start_date": start_date,
                "end_date": end_date,
                "allocation_pct": allocation_pct,
                "approver_id": approver_id,
            }
        )
        if self._pending_count > 0:
            self._pending_count -= 1

    @workflow.signal
    async def reject_candidate(
        self, opportunity_id: str, person_id: str, reason: str = ""
    ) -> None:
        workflow.logger.info(
            "reject_candidate signal: opportunity_id=%s person_id=%s reason=%s",
            opportunity_id,
            person_id,
            reason,
        )
        self._rejected.append(
            {
                "opportunity_id": opportunity_id,
                "person_id": person_id,
                "reason": reason,
            }
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
            "approved_count": len(self._approved),
            "rejected_count": len(self._rejected),
            "shortlisted_count": len(self._shortlisted),
            "pending_count": self._pending_count,
            "approved": self._approved,
            "rejected": self._rejected,
            "shortlisted": self._shortlisted,
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
        # Step 3: Recommend candidates for each open opportunity
        # ------------------------------------------------------------------
        self._status = "searching_candidates"
        recommendation_notification_ids: list[str] = []
        opp_summaries: list[dict[str, Any]] = []
        region = team.get("region")

        for opp_stub in opportunities:
            opp_id = opp_stub.get("id", "")
            if not opp_id:
                continue

            # 3a. Fetch full opportunity details (for the notification body +
            # date defaults).
            opportunity: dict[str, Any] = await workflow.execute_activity(
                get_opportunity_by_id,
                opp_id,
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            if not opportunity:
                continue

            required_band = opportunity.get("band_required", "Analyst")

            # 3b. Agent recommendation (deterministic scorer).
            recommendation: dict[str, Any] = await workflow.execute_activity(
                agent_recommend_candidates,
                args=[opp_id, 5],
                start_to_close_timeout=_AGENT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            ranked_top = recommendation.get("top", [])

            # Map agent output into the candidate dict shape the notification
            # composer expects.
            candidates: list[dict[str, Any]] = [
                {
                    "person_uri": f"urn:person:{c.get('person_id', '')}",
                    "person_id": c.get("person_id", ""),
                    "name": c.get("name", ""),
                    "band": c.get("band", ""),
                    "region": c.get("region", ""),
                    "availability_phase": "",
                    "matched_skills": len(c.get("matched_skills", [])),
                    "score": c.get("overall_score", 0),
                    "gate_passed": c.get("gate_passed", True),
                    "factor_scores": c.get("factor_scores", {}),
                    "rationale": c.get("rationale", ""),
                }
                for c in ranked_top
            ]

            # 3c. Fallback to Postgres only if the agent returned nothing.
            if not candidates:
                workflow.logger.info(
                    "Agent returned no candidates for opp=%s — Postgres fallback",
                    opp_id,
                )
                pg_persons: list[dict[str, Any]] = await workflow.execute_activity(
                    get_available_persons_by_region,
                    args=[region or "", required_band],
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY,
                )
                candidates = [
                    {
                        "person_uri": f"urn:person:{p.get('person_id', '')}",
                        "person_id": p.get("person_id", ""),
                        "name": p.get("name", ""),
                        "band": p.get("band", ""),
                        "region": p.get("region", ""),
                        "availability_phase": p.get("availability_phase", ""),
                        "matched_skills": 0,
                        "score": 0,
                    }
                    for p in pg_persons
                ]

            # Store recommendation context for shortlisting on approval.
            self._opp_context[opp_id] = {
                "start_date": opportunity.get("start_date", ""),
                "end_date": opportunity.get("end_date", ""),
                "candidate_ids": [c.get("person_id", "") for c in candidates],
            }

            # 3d. Compose candidate recommendation notification.
            recommendation_content: dict[str, Any] = await workflow.execute_activity(
                compose_candidate_recommendation,
                args=[opportunity, candidates],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

            # 3e. Send notification to project leadership.
            notif_ids: list[str] = await workflow.execute_activity(
                create_notifications_for_leadership,
                args=[
                    project_id,
                    event_id,
                    "candidate_recommendation",
                    recommendation_content["title"],
                    recommendation_content["body"],
                    recommendation_content["metadata"],
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
                len(self._approved),
                len(self._rejected),
                self._pending_count,
            )

        # ------------------------------------------------------------------
        # Step 5: For each approval, shortlist via the agent activity. The DB
        # trigger + pg_listener then start AssignmentApprovalWorkflow exactly
        # once. We do NOT start the child workflow here (fix #2).
        # ------------------------------------------------------------------
        self._status = "processing_approvals"

        for approval in self._approved:
            opp_id = approval["opportunity_id"]
            person_id = approval["person_id"]
            ctx = self._opp_context.get(opp_id, {})
            start_date = approval.get("start_date") or ctx.get("start_date") or ""
            end_date = approval.get("end_date") or ctx.get("end_date") or None
            allocation_pct = float(approval.get("allocation_pct") or 100)
            approver_id = approval.get("approver_id") or None

            if not (opp_id and person_id and start_date):
                workflow.logger.warning(
                    "Skipping incomplete approval: opp=%s person=%s start=%s",
                    opp_id,
                    person_id,
                    start_date,
                )
                continue

            try:
                shortlist_result: dict[str, Any] = await workflow.execute_activity(
                    agent_shortlist_candidate,
                    args=[
                        opp_id,
                        person_id,
                        start_date,
                        end_date,
                        allocation_pct,
                        approver_id,
                        f"Shortlisted via approval by {approver_id}",
                    ],
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY,
                )
                self._shortlisted.append(shortlist_result)
                workflow.logger.info(
                    "Shortlisted person=%s for opp=%s → assignment=%s "
                    "(approval workflow auto-starts via trigger)",
                    person_id,
                    opp_id,
                    shortlist_result.get("assignment_id"),
                )
            except Exception as exc:  # noqa: BLE001
                workflow.logger.warning(
                    "Shortlist failed for opp=%s person=%s: %s", opp_id, person_id, exc
                )

        self._status = "complete"
        return {
            "status": "complete",
            "team_id": team_id,
            "project_id": project_id,
            "opportunities_processed": len(opp_summaries),
            "opportunity_summaries": opp_summaries,
            "recommendation_notification_ids": recommendation_notification_ids,
            "approved_count": len(self._approved),
            "rejected_count": len(self._rejected),
            "shortlisted_count": len(self._shortlisted),
            "shortlisted": self._shortlisted,
        }
