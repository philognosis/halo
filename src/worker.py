"""
Temporal worker entry point for the Ontology-Driven Agentic Staffing System.

Registers all workflows and activities, then runs the worker until cancelled.

Usage:
  python -m src.worker
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


async def main() -> None:
    """Initialise DB pool, connect to Temporal, start the worker."""

    # ------------------------------------------------------------------
    # 1. Initialise asyncpg connection pool
    # ------------------------------------------------------------------
    from src.activities.db_activities import init_db_pool  # noqa: PLC0415

    logger.info("Initialising asyncpg pool: %s", settings.DATABASE_URL)
    await init_db_pool(settings.DATABASE_URL)
    logger.info("asyncpg pool ready")

    # ------------------------------------------------------------------
    # 2. Connect to Temporal
    # ------------------------------------------------------------------
    logger.info(
        "Connecting to Temporal at %s (namespace=%s) …",
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_NAMESPACE,
    )
    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    logger.info("Temporal client connected")

    # ------------------------------------------------------------------
    # 3. Import all workflow and activity modules
    # ------------------------------------------------------------------
    # Workflows
    from src.workflows.approval_workflow import AssignmentApprovalWorkflow  # noqa: PLC0415
    from src.workflows.project_workflow import ProjectOnboardingWorkflow  # noqa: PLC0415
    from src.workflows.staffing_workflow import TeamStaffingWorkflow  # noqa: PLC0415

    # Activities — db
    from src.activities.db_activities import (  # noqa: PLC0415
        create_notification,
        create_notifications_for_leadership,
        get_assignment_by_id,
        get_available_persons_by_region,
        get_opportunity_by_id,
        get_person_availability,
        get_project_by_id,
        get_team_by_id,
        mark_domain_event_processed,
        update_assignment_status,
        update_opportunity_status,
    )

    # Activities — sparql
    from src.activities.sparql_activities import (  # noqa: PLC0415
        check_availability_in_jena,
        project_allocation_to_abox,
        resolve_skos_label,
        run_preflight_shacl,
        search_candidates,
    )

    # Activities — notification
    from src.activities.notification_activities import (  # noqa: PLC0415
        compose_approval_request,
        compose_candidate_recommendation,
        compose_team_nudge,
    )

    # Activities — shacl
    from src.activities.shacl_activities import validate_allocation_preflight  # noqa: PLC0415

    # ------------------------------------------------------------------
    # 4. Create and run the worker
    # ------------------------------------------------------------------
    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[
            ProjectOnboardingWorkflow,
            TeamStaffingWorkflow,
            AssignmentApprovalWorkflow,
        ],
        activities=[
            # DB activities
            get_project_by_id,
            get_team_by_id,
            get_opportunity_by_id,
            get_assignment_by_id,
            get_person_availability,
            get_available_persons_by_region,
            create_notification,
            create_notifications_for_leadership,
            update_assignment_status,
            update_opportunity_status,
            mark_domain_event_processed,
            # SPARQL activities
            search_candidates,
            check_availability_in_jena,
            run_preflight_shacl,
            project_allocation_to_abox,
            resolve_skos_label,
            # Notification composition activities
            compose_team_nudge,
            compose_candidate_recommendation,
            compose_approval_request,
            # SHACL preflight activity
            validate_allocation_preflight,
        ],
    )

    logger.info(
        "Starting worker on task_queue=%s …", settings.TEMPORAL_TASK_QUEUE
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
