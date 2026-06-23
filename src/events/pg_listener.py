"""
PostgreSQL LISTEN/NOTIFY → Temporal workflow starter.

Connects to Postgres, listens on the 'staffing_events' channel and starts
the appropriate Temporal workflow for each domain event received.

Event payload format (from fn_emit_domain_event trigger):
  {event_id, event_type, aggregate_type, aggregate_id}

Reconnection logic uses exponential backoff capped at 60 seconds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg
from temporalio.client import Client, WorkflowIdReusePolicy

from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pg_listener")

# ---------------------------------------------------------------------------
# Workflow routing table
# ---------------------------------------------------------------------------
# Maps event_type to (workflow_class_name, workflow_id_prefix)
# Actual class references are imported lazily to avoid sandbox issues during
# listener-only execution.
WORKFLOW_ROUTES: dict[str, tuple[str, str]] = {
    "project_INSERT": ("ProjectOnboardingWorkflow", "project-onboarding"),
    "project_UPDATE": ("ProjectOnboardingWorkflow", "project-onboarding"),
    "team_INSERT": ("TeamStaffingWorkflow", "team-staffing"),
    "opportunity_INSERT": ("OpportunityFillWorkflow", "opportunity-fill"),
    "assignment_INSERT": ("AssignmentApprovalWorkflow", "assignment-approval"),
    "assignment_UPDATE": ("AssignmentApprovalWorkflow", "assignment-approval"),
}


async def start_workflow(
    temporal_client: Client,
    event: dict[str, Any],
) -> None:
    """Dispatch a Temporal workflow based on the event_type."""
    event_type: str = event.get("event_type", "")
    aggregate_id: str = str(event.get("aggregate_id", ""))
    event_id: str = str(event.get("event_id", ""))

    route = WORKFLOW_ROUTES.get(event_type)
    if route is None:
        logger.debug("No workflow route for event_type=%s — skipping", event_type)
        return

    workflow_name, id_prefix = route
    workflow_id = f"{id_prefix}-{aggregate_id}"

    # project_UPDATE uses ALLOW_DUPLICATE_FAILED_ONLY for idempotency
    reuse_policy = (
        WorkflowIdReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
        if event_type == "project_UPDATE"
        else WorkflowIdReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    )

    try:
        handle = await temporal_client.start_workflow(
            workflow_name,
            args=[aggregate_id, event_id],
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            id_reuse_policy=reuse_policy,
        )
        logger.info(
            "Started workflow %s (run_id=%s) for event_type=%s aggregate_id=%s",
            workflow_id,
            handle.result_run_id,
            event_type,
            aggregate_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to start workflow %s for event_id=%s: %s",
            workflow_id,
            event_id,
            exc,
        )


async def listen_loop(temporal_client: Client) -> None:
    """
    Core LISTEN loop. Connects to Postgres, registers the LISTEN and
    dispatches workflow starts on each notification.

    Exits on unrecoverable errors so the caller can retry with backoff.
    """
    conn: asyncpg.Connection = await asyncpg.connect(settings.DATABASE_URL)
    logger.info("Connected to PostgreSQL, registering LISTEN staffing_events")

    async def notification_handler(
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        logger.info("Received notification on channel=%s payload=%s", channel, payload)
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse notification payload: %s — raw=%s", exc, payload)
            return
        await start_workflow(temporal_client, event)

    await conn.add_listener("staffing_events", notification_handler)
    logger.info("Listening on staffing_events — waiting for domain events …")

    try:
        # Keep the connection alive; asyncpg will call notification_handler
        # for every pg_notify received.
        while True:
            await asyncio.sleep(5)
            # Send a lightweight keepalive so the TCP connection stays open.
            await conn.execute("SELECT 1")
    finally:
        await conn.remove_listener("staffing_events", notification_handler)
        await conn.close()
        logger.info("PostgreSQL connection closed")


async def main() -> None:
    """
    Entry point. Connects to Temporal then enters the LISTEN loop with
    exponential-backoff reconnection on failure.
    """
    logger.info("Connecting to Temporal at %s …", settings.TEMPORAL_HOST)
    temporal_client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    logger.info("Temporal client connected (namespace=%s)", settings.TEMPORAL_NAMESPACE)

    backoff = 2.0
    max_backoff = 60.0

    while True:
        try:
            await listen_loop(temporal_client)
        except asyncpg.PostgresConnectionStatusError as exc:
            logger.warning("PostgreSQL connection lost: %s", exc)
        except asyncpg.PostgresError as exc:
            logger.error("PostgreSQL error: %s", exc)
        except asyncio.CancelledError:
            logger.info("Listener cancelled — shutting down")
            break
        except Exception as exc:
            logger.error("Unexpected error in listen loop: %s", exc, exc_info=True)

        logger.info("Reconnecting in %.0f seconds …", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


if __name__ == "__main__":
    asyncio.run(main())
