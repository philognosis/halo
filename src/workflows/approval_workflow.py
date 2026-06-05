"""
AssignmentApprovalWorkflow — HITL approval gate for a proposed assignment.

Flow:
  1. Fetch assignment details (person + opportunity)
  2. Run preflight SHACL validation
  3. If hard violations → cancel assignment, return rejected
  4. Compose approval request notification (include any warnings)
  5. Send notification to project leadership
  6. Mark domain event processed
  7. Wait up to 5 days for approve/reject signal
  8. On timeout → escalate → wait 2 more days → auto-reject if still no decision
  9. On approve:
       - update_assignment_status → 'staffed'
       - update_opportunity_status → 'filled'
       - project_allocation_to_abox → write to Jena ABox
       - send assignment_confirmed notification to the assigned person
  10. On reject:
       - update_assignment_status → 'cancelled'
       - send notification to leadership of rejection

Signals:
  - approve(approver_id, notes="")
  - reject(approver_id, reason)

Queries:
  - get_decision() → current decision state
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.activities.db_activities import (
        create_notification,
        create_notifications_for_leadership,
        get_assignment_by_id,
        get_opportunity_by_id,
        get_person_availability,
        mark_domain_event_processed,
        update_assignment_status,
        update_opportunity_status,
    )
    from src.activities.notification_activities import compose_approval_request
    from src.activities.shacl_activities import validate_allocation_preflight
    from src.activities.sparql_activities import project_allocation_to_abox
    from src.config import settings as _settings

# ---------------------------------------------------------------------------
# Retry / timeout config
# ---------------------------------------------------------------------------
_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)

# HITL windows
_INITIAL_WAIT = timedelta(days=5)
_ESCALATION_WAIT = timedelta(days=2)


@workflow.defn(name="AssignmentApprovalWorkflow")
class AssignmentApprovalWorkflow:
    """
    Durable HITL workflow that waits for a human approval signal before
    confirming a staffing assignment.
    """

    def __init__(self) -> None:
        self._decision: str | None = None          # 'approved' | 'rejected'
        self._approver_id: str | None = None
        self._rejection_reason: str | None = None
        self._notes: str = ""

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    @workflow.signal
    async def approve(self, approver_id: str, notes: str = "") -> None:
        workflow.logger.info(
            "approve signal received: approver_id=%s notes=%r", approver_id, notes
        )
        self._decision = "approved"
        self._approver_id = approver_id
        self._notes = notes

    @workflow.signal
    async def reject(self, approver_id: str, reason: str) -> None:
        workflow.logger.info(
            "reject signal received: approver_id=%s reason=%r", approver_id, reason
        )
        self._decision = "rejected"
        self._approver_id = approver_id
        self._rejection_reason = reason

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @workflow.query
    def get_decision(self) -> dict[str, Any]:
        return {
            "decision": self._decision,
            "approver_id": self._approver_id,
            "rejection_reason": self._rejection_reason,
            "notes": self._notes,
        }

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------
    @workflow.run
    async def run(self, assignment_id: str, event_id: str) -> dict[str, Any]:
        workflow.logger.info(
            "AssignmentApprovalWorkflow started: assignment_id=%s event_id=%s",
            assignment_id,
            event_id,
        )

        # ------------------------------------------------------------------
        # Step 1: Fetch assignment details
        # ------------------------------------------------------------------
        assignment: dict[str, Any] = await workflow.execute_activity(
            get_assignment_by_id,
            assignment_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        if not assignment:
            workflow.logger.warning(
                "AssignmentApprovalWorkflow: assignment %s not found — aborting",
                assignment_id,
            )
            return {
                "status": "aborted",
                "reason": "assignment_not_found",
                "assignment_id": assignment_id,
            }

        person_id = assignment.get("person_id", "")
        opportunity_id = assignment.get("opportunity_id", "")
        project_id = assignment.get("project_id", "")
        start_date = assignment.get("start_date", "")
        end_date = assignment.get("end_date") or assignment.get("opp_end_date") or ""
        allocation_pct = float(assignment.get("allocation_pct", 100))

        # ------------------------------------------------------------------
        # Step 2: Preflight SHACL validation
        # ------------------------------------------------------------------
        preflight: dict[str, Any] = await workflow.execute_activity(
            validate_allocation_preflight,
            args=[person_id, opportunity_id, start_date, end_date, allocation_pct],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        can_proceed: bool = preflight.get("can_proceed", True)
        violations: list[str] = preflight.get("violations", [])
        warnings: list[str] = preflight.get("warnings", [])
        recommendation: str = preflight.get("recommendation", "")

        # ------------------------------------------------------------------
        # Step 3: Hard violations → auto-reject immediately
        # ------------------------------------------------------------------
        if not can_proceed:
            violations_str = "; ".join(violations)
            workflow.logger.warning(
                "Preflight violations for assignment=%s: %s", assignment_id, violations_str
            )
            await workflow.execute_activity(
                update_assignment_status,
                args=[assignment_id, "cancelled", f"Auto-rejected: {violations_str}"],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            await workflow.execute_activity(
                mark_domain_event_processed,
                args=[event_id, violations_str],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            return {
                "status": "rejected",
                "reason": "preflight_violations",
                "violations": violations,
                "assignment_id": assignment_id,
                "decided_by": "system",
            }

        # ------------------------------------------------------------------
        # Step 4 + 5: Compose approval request (include warnings if any)
        # ------------------------------------------------------------------

        # Fetch full opportunity for skills/qualifications display
        opportunity: dict[str, Any] = await workflow.execute_activity(
            get_opportunity_by_id,
            opportunity_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # Build a person-like dict from the denormalised assignment row
        person_dict = {
            "name": assignment.get("person_name", ""),
            "email": assignment.get("person_email", ""),
            "band": assignment.get("person_band", ""),
            "region": assignment.get("person_region", ""),
            "office": assignment.get("person_office", ""),
            "status": assignment.get("person_status", ""),
        }

        notification_content: dict[str, Any] = await workflow.execute_activity(
            compose_approval_request,
            args=[assignment, opportunity, person_dict],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # Append warnings to body if present
        if warnings:
            warning_text = "\n\nWarnings (non-blocking):\n" + "\n".join(
                f"  - {w}" for w in warnings
            )
            notification_content["body"] = notification_content["body"] + warning_text
            notification_content["metadata"]["warnings"] = warnings

        # ------------------------------------------------------------------
        # Step 6: Notify leadership
        # ------------------------------------------------------------------
        notif_ids: list[str] = await workflow.execute_activity(
            create_notifications_for_leadership,
            args=[
                project_id,
                event_id,
                "approval_request",
                notification_content["title"],
                notification_content["body"],
                notification_content["metadata"],
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        workflow.logger.info(
            "Approval request sent to %d leader(s): %s", len(notif_ids), notif_ids
        )

        # ------------------------------------------------------------------
        # Step 7: Mark domain event processed (after notification sent)
        # ------------------------------------------------------------------
        await workflow.execute_activity(
            mark_domain_event_processed,
            args=[event_id, None],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # ------------------------------------------------------------------
        # Step 8: Wait up to 5 days for approve/reject signal
        # ------------------------------------------------------------------
        workflow.logger.info(
            "Waiting up to 5 days for approval signal on assignment=%s", assignment_id
        )
        decision_received = await workflow.wait_condition(
            lambda: self._decision is not None,
            timeout=_INITIAL_WAIT,
        )

        # ------------------------------------------------------------------
        # Step 9: Handle timeout → escalate → wait 2 more days
        # ------------------------------------------------------------------
        if not decision_received:
            workflow.logger.warning(
                "No decision after 5 days for assignment=%s — escalating", assignment_id
            )

            escalation_title = f"[ESCALATION] {notification_content['title']}"
            escalation_body = (
                "ESCALATION: 5 days have passed without a decision on this assignment "
                "approval request. Auto-rejection will occur in 2 days if no action is taken.\n\n"
                + notification_content["body"]
            )

            await workflow.execute_activity(
                create_notifications_for_leadership,
                args=[
                    project_id,
                    event_id,
                    "approval_request",
                    escalation_title,
                    escalation_body,
                    {**notification_content["metadata"], "escalation": True},
                ],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

            # Wait 2 more days
            decision_received = await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=_ESCALATION_WAIT,
            )

            if not decision_received:
                # Auto-reject
                workflow.logger.warning(
                    "Auto-rejecting assignment=%s after 7-day total wait", assignment_id
                )
                self._decision = "rejected"
                self._rejection_reason = "Auto-rejected: no decision received within 7 days."
                self._approver_id = "system"

        # ------------------------------------------------------------------
        # Step 10: Process the decision
        # ------------------------------------------------------------------
        if self._decision == "approved":
            return await self._handle_approval(
                assignment_id=assignment_id,
                person_id=person_id,
                opportunity_id=opportunity_id,
                project_id=project_id,
                start_date=start_date,
                end_date=end_date,
                allocation_pct=allocation_pct,
                assignment=assignment,
                notification_content=notification_content,
            )
        else:
            return await self._handle_rejection(
                assignment_id=assignment_id,
                project_id=project_id,
                event_id=event_id,
                notification_content=notification_content,
            )

    # ------------------------------------------------------------------
    # Private helpers — approval path
    # ------------------------------------------------------------------
    async def _handle_approval(
        self,
        assignment_id: str,
        person_id: str,
        opportunity_id: str,
        project_id: str,
        start_date: str,
        end_date: str,
        allocation_pct: float,
        assignment: dict[str, Any],
        notification_content: dict[str, Any],
    ) -> dict[str, Any]:
        workflow.logger.info(
            "Processing APPROVAL for assignment=%s by approver=%s",
            assignment_id,
            self._approver_id,
        )

        # 10a. Update assignment status → staffed
        await workflow.execute_activity(
            update_assignment_status,
            args=[assignment_id, "staffed", self._notes or f"Approved by {self._approver_id}"],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # 10b. Update opportunity status → filled
        await workflow.execute_activity(
            update_opportunity_status,
            args=[opportunity_id, "filled"],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # 10c. Write allocation to Jena ABox
        person_uri = f"{_settings.STF_NAMESPACE}person/{person_id}"
        opportunity_uri = f"{_settings.STF_NAMESPACE}opportunity/{opportunity_id}"

        abox_written: bool = await workflow.execute_activity(
            project_allocation_to_abox,
            args=[
                assignment_id,
                person_uri,
                opportunity_uri,
                start_date,
                end_date,
                allocation_pct,
            ],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        workflow.logger.info(
            "ABox write for assignment=%s: success=%s", assignment_id, abox_written
        )

        # 10d. Send confirmation notification to the assigned person
        confirm_title = (
            f"You've been confirmed: {assignment.get('role_title', 'New Role')}"
        )
        confirm_body = (
            f"Congratulations! Your assignment has been confirmed.\n\n"
            f"Role:       {assignment.get('role_title', '')}\n"
            f"Start Date: {start_date}\n"
            f"End Date:   {end_date or 'TBD'}\n"
            f"Allocation: {allocation_pct:.0f}%\n\n"
            f"Approved by: {self._approver_id}\n"
            + (f"Notes: {self._notes}" if self._notes else "")
        )
        confirm_metadata = {
            "assignment_id": assignment_id,
            "opportunity_id": opportunity_id,
            "approved_by": self._approver_id,
            "abox_written": abox_written,
        }

        await workflow.execute_activity(
            create_notification,
            args=[
                person_id,
                "",  # no specific event_id for the confirmation
                "assignment_confirmed",
                confirm_title,
                confirm_body,
                confirm_metadata,
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        return {
            "status": "approved",
            "assignment_id": assignment_id,
            "decided_by": self._approver_id,
            "abox_written": abox_written,
        }

    # ------------------------------------------------------------------
    # Private helpers — rejection path
    # ------------------------------------------------------------------
    async def _handle_rejection(
        self,
        assignment_id: str,
        project_id: str,
        event_id: str,
        notification_content: dict[str, Any],
    ) -> dict[str, Any]:
        workflow.logger.info(
            "Processing REJECTION for assignment=%s by approver=%s reason=%r",
            assignment_id,
            self._approver_id,
            self._rejection_reason,
        )

        reason = self._rejection_reason or "No reason provided"

        # 11a. Update assignment status → cancelled
        await workflow.execute_activity(
            update_assignment_status,
            args=[assignment_id, "cancelled", reason],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # 11b. Notify leadership of rejection
        reject_title = f"[Rejected] {notification_content['title']}"
        reject_body = (
            f"The following assignment has been rejected.\n\n"
            f"Rejected by: {self._approver_id}\n"
            f"Reason: {reason}\n\n"
            + notification_content["body"]
        )

        await workflow.execute_activity(
            create_notifications_for_leadership,
            args=[
                project_id,
                event_id,
                "assignment_cancelled",
                reject_title,
                reject_body,
                {
                    **notification_content.get("metadata", {}),
                    "rejected_by": self._approver_id,
                    "rejection_reason": reason,
                },
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        return {
            "status": "rejected",
            "assignment_id": assignment_id,
            "decided_by": self._approver_id,
            "reason": reason,
        }
