"""
OpportunityFillWorkflow — triggered by opportunity_INSERT events (reconciliation
fix #1: the route existed in pg_listener but the workflow was never implemented).

Flow:
  1. Fetch the opportunity by id.
  2. If status != 'open' → mark the event processed and return.
  3. Run the agent recommender (agent_recommend_candidates).
  4. Compose a candidate-recommendation nudge to project leadership.
  5. Mark the domain event processed.

All I/O happens in activities. Activity imports go through
``workflow.unsafe.imports_passed_through()``.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.activities.db_activities import (
        create_notifications_for_leadership,
        get_opportunity_by_id,
        mark_domain_event_processed,
    )
    from src.agents.activities import agent_recommend_candidates

# ---------------------------------------------------------------------------
# Shared retry / timeout config (mirrors the other workflows)
# ---------------------------------------------------------------------------
_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_AGENT_TIMEOUT = timedelta(seconds=60)


@workflow.defn(name="OpportunityFillWorkflow")
class OpportunityFillWorkflow:
    """Recommend candidates for a newly opened opportunity and nudge leadership."""

    @workflow.run
    async def run(self, opportunity_id: str, event_id: str) -> dict[str, Any]:
        workflow.logger.info(
            "OpportunityFillWorkflow started: opportunity_id=%s event_id=%s",
            opportunity_id,
            event_id,
        )

        # ------------------------------------------------------------------
        # Step 1: Fetch the opportunity
        # ------------------------------------------------------------------
        opportunity: dict[str, Any] = await workflow.execute_activity(
            get_opportunity_by_id,
            opportunity_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        if not opportunity:
            workflow.logger.warning(
                "OpportunityFillWorkflow: opportunity %s not found — aborting",
                opportunity_id,
            )
            await workflow.execute_activity(
                mark_domain_event_processed,
                args=[event_id, "opportunity_not_found"],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            return {
                "status": "aborted",
                "reason": "opportunity_not_found",
                "opportunity_id": opportunity_id,
            }

        project_id: str = opportunity.get("project_id", "")

        # ------------------------------------------------------------------
        # Step 2: Only act on OPEN opportunities (trigger also fires on UPDATE)
        # ------------------------------------------------------------------
        if opportunity.get("status") != "open":
            workflow.logger.info(
                "Opportunity %s is not open (status=%s) — nothing to do",
                opportunity_id,
                opportunity.get("status"),
            )
            await workflow.execute_activity(
                mark_domain_event_processed,
                args=[event_id, None],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )
            return {
                "status": "skipped",
                "reason": f"opportunity_status_{opportunity.get('status')}",
                "opportunity_id": opportunity_id,
            }

        # ------------------------------------------------------------------
        # Step 3: Run the agent recommender
        # ------------------------------------------------------------------
        recommendation: dict[str, Any] = await workflow.execute_activity(
            agent_recommend_candidates,
            args=[opportunity_id, 5],
            start_to_close_timeout=_AGENT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        top = recommendation.get("top", [])

        # ------------------------------------------------------------------
        # Step 4: Compose + send a candidate-recommendation nudge to leadership
        # ------------------------------------------------------------------
        role_title = opportunity.get("role_title", "an open role")
        title = f"Candidate recommendations: {role_title}"
        if top:
            body_lines = [
                f"The recommendation agent surfaced {len(top)} candidate(s) for "
                f"the open opportunity '{role_title}':",
                "",
            ]
            for c in top:
                note = "" if c.get("gate_passed") else " (does not meet all mandatory requirements)"
                body_lines.append(
                    f"  - {c.get('name')} ({c.get('band')}, {c.get('region')}) — "
                    f"score {c.get('overall_score')}{note}"
                )
            body = "\n".join(body_lines)
        else:
            body = (
                f"The open opportunity '{role_title}' has no matching candidates "
                f"yet. Consider relaxing the requirements or broadening the search."
            )

        metadata = {
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "candidate_count": len(top),
            "top_candidates": top,
        }

        notif_ids: list[str] = []
        if project_id:
            notif_ids = await workflow.execute_activity(
                create_notifications_for_leadership,
                args=[
                    project_id,
                    event_id,
                    "candidate_recommendation",
                    title,
                    body,
                    metadata,
                ],
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

        # ------------------------------------------------------------------
        # Step 5: Mark the domain event processed
        # ------------------------------------------------------------------
        await workflow.execute_activity(
            mark_domain_event_processed,
            args=[event_id, None],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        workflow.logger.info(
            "OpportunityFillWorkflow complete: opportunity=%s candidates=%d notifications=%d",
            opportunity_id,
            len(top),
            len(notif_ids),
        )

        return {
            "status": "complete",
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "candidate_count": len(top),
            "notification_ids": notif_ids,
        }
