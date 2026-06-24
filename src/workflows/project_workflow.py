"""
ProjectOnboardingWorkflow — triggered by project_INSERT / project_UPDATE events.

Flow:
  1. Fetch project + leadership from Postgres
  2. Mark domain event processed
  3. Compose and send nudge notification to all project leaders
  4. Wait 72 hours (durable timer via asyncio.sleep — intercepted by Temporal)
  5. Re-check: if still no team, send escalation nudge

Temporal sandbox restrictions:
  - No direct asyncpg / httpx imports at module level
  - All I/O through activity calls
  - Use workflow.logger (not stdlib logging) inside the workflow body
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    # These are referenced only for type annotations resolved at import time;
    # actual calls go through execute_activity, so they are safe here.
    from src.activities.db_activities import (
        create_notifications_for_leadership,
        get_project_by_id,
        mark_domain_event_processed,
    )
    from src.activities.notification_activities import compose_team_nudge
    from src.agents.activities import agent_propose_team_shape, agent_team_composition_debate

_AGENT_TIMEOUT = timedelta(seconds=60)

# ---------------------------------------------------------------------------
# Shared retry policy for all activities in this workflow
# ---------------------------------------------------------------------------
_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)


@workflow.defn(name="ProjectOnboardingWorkflow")
class ProjectOnboardingWorkflow:
    """
    Durable workflow that nudges project leadership to create a team after a
    project is registered in the system.
    """

    @workflow.run
    async def run(self, project_id: str, event_id: str) -> dict[str, Any]:
        workflow.logger.info(
            "ProjectOnboardingWorkflow started: project_id=%s event_id=%s",
            project_id,
            event_id,
        )

        # ------------------------------------------------------------------
        # Step 1: Fetch project details
        # ------------------------------------------------------------------
        project: dict[str, Any] = await workflow.execute_activity(
            get_project_by_id,
            project_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        if not project:
            workflow.logger.warning(
                "ProjectOnboardingWorkflow: project %s not found — aborting", project_id
            )
            return {"status": "aborted", "reason": "project_not_found", "project_id": project_id}

        workflow.logger.info(
            "Fetched project: %s (%s) for client %s",
            project.get("project_name"),
            project.get("unique_code"),
            project.get("client"),
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
        # Step 3: Compose team nudge notification content
        # ------------------------------------------------------------------
        nudge: dict[str, Any] = await workflow.execute_activity(
            compose_team_nudge,
            project,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        # ------------------------------------------------------------------
        # Step 3b: Run multi-agent team composition debate for an enriched
        # proposal. Falls back to the simple deterministic proposal.
        # ------------------------------------------------------------------
        debate_result: dict[str, Any] = {}
        try:
            debate_result = await workflow.execute_activity(
                agent_team_composition_debate,
                project_id,
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:  # noqa: BLE001
            workflow.logger.warning(
                "agent_team_composition_debate failed for project=%s: %s — "
                "falling back to simple proposal", project_id, exc,
            )

        debate_roles = debate_result.get("roles", [])

        if not debate_roles:
            try:
                team_shape = await workflow.execute_activity(
                    agent_propose_team_shape,
                    project_id,
                    start_to_close_timeout=_AGENT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except Exception as exc:  # noqa: BLE001
                workflow.logger.warning(
                    "agent_propose_team_shape failed for project=%s: %s", project_id, exc
                )
                team_shape = {}

            suggested_team = team_shape.get("suggested_team") if team_shape else None
            if suggested_team and suggested_team.get("opportunities"):
                role_lines = [
                    f"  - {o['role_title']} ({o['band_required']}, {o['role_category']}): "
                    f"{o['rationale']}"
                    for o in suggested_team["opportunities"]
                ]
                nudge["body"] = (
                    nudge["body"]
                    + "\n\nSuggested team structure:\n"
                    + "\n".join(role_lines)
                )
                nudge["metadata"] = {
                    **nudge.get("metadata", {}),
                    "suggested_team": suggested_team,
                }
        else:
            role_lines = [
                f"  - {r.get('role', '?')} x{r.get('count', 1)}: {r.get('rationale', '')}"
                for r in debate_roles
            ]
            nudge["body"] = (
                nudge["body"]
                + f"\n\nSuggested team structure ({debate_result.get('debate_rounds', 1)} "
                f"debate round(s), {debate_result.get('total_fte', 0)} FTE):\n"
                + "\n".join(role_lines)
            )
            nudge["metadata"] = {
                **nudge.get("metadata", {}),
                "debate_result": debate_result,
            }

        # ------------------------------------------------------------------
        # Step 4: Send initial nudge to all project leaders
        # ------------------------------------------------------------------
        notification_ids: list[str] = await workflow.execute_activity(
            create_notifications_for_leadership,
            args=[
                project_id,
                event_id,
                "nudge_create_team",
                nudge["title"],
                nudge["body"],
                nudge["metadata"],
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        workflow.logger.info(
            "Initial team-nudge sent to %d leader(s): %s",
            len(notification_ids),
            notification_ids,
        )

        # ------------------------------------------------------------------
        # Step 5: Wait 72 hours for team creation
        # ------------------------------------------------------------------
        workflow.logger.info(
            "Sleeping 72 hours before escalation check for project=%s", project_id
        )
        await asyncio.sleep(72 * 3600)  # resolved via workflow.unsafe context

        # ------------------------------------------------------------------
        # Step 6: Re-check if team was created
        # ------------------------------------------------------------------
        refreshed_project: dict[str, Any] = await workflow.execute_activity(
            get_project_by_id,
            project_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        teams = refreshed_project.get("teams", [])

        if teams:
            workflow.logger.info(
                "Team(s) have been created for project=%s — no escalation needed",
                project_id,
            )
            return {
                "status": "team_created",
                "project_id": project_id,
                "notification_ids": notification_ids,
                "teams_created": len(teams),
            }

        # ------------------------------------------------------------------
        # Step 7: Send escalation nudge
        # ------------------------------------------------------------------
        workflow.logger.warning(
            "No team created after 72h for project=%s — sending escalation nudge",
            project_id,
        )

        escalation_nudge_meta = dict(nudge["metadata"])
        escalation_nudge_meta["escalation"] = True
        escalation_nudge_meta["escalation_reason"] = "no_team_after_72h"

        escalation_title = f"[ESCALATION] {nudge['title']}"
        escalation_body = (
            f"ESCALATION NOTICE: 72 hours have passed and no team has been defined "
            f"for the following project.\n\n{nudge['body']}"
        )

        escalation_ids: list[str] = await workflow.execute_activity(
            create_notifications_for_leadership,
            args=[
                project_id,
                event_id,
                "nudge_create_team",
                escalation_title,
                escalation_body,
                escalation_nudge_meta,
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        workflow.logger.info(
            "Escalation nudge sent to %d leader(s): %s", len(escalation_ids), escalation_ids
        )

        return {
            "status": "escalated",
            "project_id": project_id,
            "initial_notification_ids": notification_ids,
            "escalation_notification_ids": escalation_ids,
            "teams_created": 0,
        }
