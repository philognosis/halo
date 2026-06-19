"""
Database activities for the Staffing System Temporal worker.

All I/O is performed through asyncpg. The module-level `_pool` variable is
initialised by the worker at startup via `init_db_pool()` and is available
to every activity as a closure over the module global.

Activity functions are decorated with @activity.defn and return plain dicts
that are JSON-serialisable so that Temporal can serialise/deserialise them
across workflow state boundaries.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import asyncpg
from temporalio import activity

logger = logging.getLogger(__name__)

# Module-level pool — set by worker.py before registering activities.
_pool: asyncpg.Pool | None = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised. Call init_db_pool() first.")
    return _pool


async def init_db_pool(dsn: str) -> asyncpg.Pool:
    """Create and store the module-level connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    logger.info("asyncpg pool created (min=2, max=10)")
    return _pool


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed")


# ---------------------------------------------------------------------------
# Activity: get_project_by_id
# ---------------------------------------------------------------------------
@activity.defn(name="get_project_by_id")
async def get_project_by_id(project_id: str) -> dict[str, Any]:
    """Fetch a project row together with its leadership entries."""
    activity.logger.info("get_project_by_id: project_id=%s", project_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        project_row = await conn.fetchrow(
            """
            SELECT
                p.id, p.unique_code, p.client, p.project_name,
                p.start_date::TEXT, p.end_date::TEXT,
                p.industry, p.sector, p.function, p.region, p.status,
                p.created_at::TEXT, p.updated_at::TEXT
            FROM project p
            WHERE p.id = $1::UUID
            """,
            project_id,
        )
        if project_row is None:
            activity.logger.warning("No project found for id=%s", project_id)
            return {}

        leadership_rows = await conn.fetch(
            """
            SELECT
                l.id, l.role,
                l.person_id::TEXT,
                per.name AS person_name,
                per.email AS person_email
            FROM leadership l
            JOIN person per ON per.id = l.person_id
            WHERE l.project_id = $1::UUID
            ORDER BY l.role
            """,
            project_id,
        )

        teams_rows = await conn.fetch(
            """
            SELECT id::TEXT, name, team_lead_id::TEXT
            FROM team
            WHERE project_id = $1::UUID
            ORDER BY created_at
            """,
            project_id,
        )

        result = dict(project_row)
        result["id"] = str(result["id"])
        result["leadership"] = [dict(r) for r in leadership_rows]
        for leader in result["leadership"]:
            leader["id"] = str(leader["id"])
        result["teams"] = [dict(r) for r in teams_rows]
        return result


# ---------------------------------------------------------------------------
# Activity: get_team_by_id
# ---------------------------------------------------------------------------
@activity.defn(name="get_team_by_id")
async def get_team_by_id(team_id: str) -> dict[str, Any]:
    """Fetch a team row with its parent project and open opportunities."""
    activity.logger.info("get_team_by_id: team_id=%s", team_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        team_row = await conn.fetchrow(
            """
            SELECT
                t.id, t.name, t.project_id::TEXT, t.team_lead_id::TEXT,
                t.created_at::TEXT,
                p.project_name, p.client, p.start_date::TEXT, p.end_date::TEXT,
                p.status AS project_status, p.industry, p.region
            FROM team t
            JOIN project p ON p.id = t.project_id
            WHERE t.id = $1::UUID
            """,
            team_id,
        )
        if team_row is None:
            activity.logger.warning("No team found for id=%s", team_id)
            return {}

        opps = await conn.fetch(
            """
            SELECT
                o.id::TEXT, o.role_title, o.description,
                o.band_required, o.start_date::TEXT, o.end_date::TEXT,
                o.status, o.notes
            FROM opportunity o
            WHERE o.team_id = $1::UUID AND o.status = 'open'
            ORDER BY o.created_at
            """,
            team_id,
        )

        result = dict(team_row)
        result["id"] = str(result["id"])
        result["opportunities"] = [dict(r) for r in opps]
        return result


# ---------------------------------------------------------------------------
# Activity: get_opportunity_by_id
# ---------------------------------------------------------------------------
@activity.defn(name="get_opportunity_by_id")
async def get_opportunity_by_id(opportunity_id: str) -> dict[str, Any]:
    """Fetch an opportunity with its required skills and qualifications."""
    activity.logger.info("get_opportunity_by_id: opportunity_id=%s", opportunity_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        opp_row = await conn.fetchrow(
            """
            SELECT
                o.id, o.team_id::TEXT, o.role_title, o.description,
                o.band_required, o.start_date::TEXT, o.end_date::TEXT,
                o.status, o.notes,
                t.project_id::TEXT
            FROM opportunity o
            JOIN team t ON t.id = o.team_id
            WHERE o.id = $1::UUID
            """,
            opportunity_id,
        )
        if opp_row is None:
            activity.logger.warning("No opportunity found for id=%s", opportunity_id)
            return {}

        skills = await conn.fetch(
            """
            SELECT
                os.id::TEXT, os.skill_id, os.skill_name,
                os.skill_type, os.min_proficiency, os.is_mandatory
            FROM opportunity_skill os
            WHERE os.opportunity_id = $1::UUID
            ORDER BY os.is_mandatory DESC, os.skill_name
            """,
            opportunity_id,
        )

        quals = await conn.fetch(
            """
            SELECT
                oq.id::TEXT, oq.qualification_level,
                oq.field_of_study, oq.is_mandatory
            FROM opportunity_qualification oq
            WHERE oq.opportunity_id = $1::UUID
            """,
            opportunity_id,
        )

        result = dict(opp_row)
        result["id"] = str(result["id"])
        result["required_skills"] = [dict(r) for r in skills]
        result["required_qualifications"] = [dict(r) for r in quals]
        return result


# ---------------------------------------------------------------------------
# Activity: get_assignment_by_id
# ---------------------------------------------------------------------------
@activity.defn(name="get_assignment_by_id")
async def get_assignment_by_id(assignment_id: str) -> dict[str, Any]:
    """Fetch an assignment with the associated person and opportunity."""
    activity.logger.info("get_assignment_by_id: assignment_id=%s", assignment_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.id, a.opportunity_id::TEXT, a.person_id::TEXT,
                a.start_date::TEXT, a.end_date::TEXT,
                a.allocation_pct, a.status, a.notes,
                a.assigned_by::TEXT, a.assigned_at::TEXT,
                -- person
                p.name AS person_name, p.email AS person_email,
                p.band AS person_band, p.region AS person_region,
                p.office AS person_office, p.status AS person_status,
                -- opportunity
                o.role_title, o.band_required,
                o.start_date::TEXT AS opp_start_date,
                o.end_date::TEXT   AS opp_end_date,
                o.description      AS opp_description,
                t.project_id::TEXT
            FROM assignment a
            JOIN person p      ON p.id = a.person_id
            JOIN opportunity o ON o.id = a.opportunity_id
            JOIN team t        ON t.id = o.team_id
            WHERE a.id = $1::UUID
            """,
            assignment_id,
        )
        if row is None:
            activity.logger.warning("No assignment found for id=%s", assignment_id)
            return {}

        result = dict(row)
        result["id"] = str(result["id"])
        return result


# ---------------------------------------------------------------------------
# Activity: get_person_availability
# ---------------------------------------------------------------------------
@activity.defn(name="get_person_availability")
async def get_person_availability(person_id: str) -> dict[str, Any]:
    """Query the person_availability view for a single person."""
    activity.logger.info("get_person_availability: person_id=%s", person_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                person_id::TEXT, name, band, region, office,
                person_status, allocated_pct, available_pct,
                active_assignment_count, availability_phase,
                next_available_date::TEXT,
                assignment_statuses
            FROM person_availability
            WHERE person_id = $1::UUID
            """,
            person_id,
        )
        if row is None:
            return {}
        result = dict(row)
        return result


# ---------------------------------------------------------------------------
# Activity: get_available_persons_by_region
# ---------------------------------------------------------------------------
@activity.defn(name="get_available_persons_by_region")
async def get_available_persons_by_region(region: str, band: str) -> list[dict[str, Any]]:
    """
    Return persons in the given region/band who are not FullyAllocated.
    Falls back gracefully to returning the list even when empty.
    """
    activity.logger.info(
        "get_available_persons_by_region: region=%s band=%s", region, band
    )
    # Band ordering for >= comparison
    band_order = [
        "Analyst", "Consultant", "Senior Consultant",
        "Manager", "Senior Manager", "Director", "Partner",
    ]
    try:
        min_band_index = band_order.index(band)
    except ValueError:
        min_band_index = 0
    eligible_bands = band_order[min_band_index:]

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pa.person_id::TEXT, pa.name, pa.band, pa.region, pa.office,
                pa.person_status, pa.allocated_pct, pa.available_pct,
                pa.availability_phase, pa.next_available_date::TEXT
            FROM person_availability pa
            WHERE pa.region = $1
              AND pa.band = ANY($2::TEXT[])
              AND pa.person_status IN ('active', 'bench')
              AND pa.availability_phase != 'FullyAllocated'
            ORDER BY pa.available_pct DESC, pa.band
            LIMIT 50
            """,
            region,
            eligible_bands,
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Activity: create_notification
# ---------------------------------------------------------------------------
@activity.defn(name="create_notification")
async def create_notification(
    recipient_id: str,
    event_id: str,
    notif_type: str,
    title: str,
    body: str,
    metadata: dict,
) -> str:
    """Insert a notification row and return its UUID as a string."""
    activity.logger.info(
        "create_notification: recipient=%s type=%s", recipient_id, notif_type
    )
    pool = get_pool()
    import json as _json

    async with pool.acquire() as conn:
        notif_id = await conn.fetchval(
            """
            INSERT INTO notification (event_id, recipient_id, type, title, body, metadata)
            VALUES ($1::UUID, $2::UUID, $3, $4, $5, $6::JSONB)
            RETURNING id::TEXT
            """,
            event_id if event_id else None,
            recipient_id,
            notif_type,
            title,
            body,
            _json.dumps(metadata),
        )
        activity.logger.info("Created notification id=%s", notif_id)
        return notif_id


# ---------------------------------------------------------------------------
# Activity: create_notifications_for_leadership
# ---------------------------------------------------------------------------
@activity.defn(name="create_notifications_for_leadership")
async def create_notifications_for_leadership(
    project_id: str,
    event_id: str,
    notif_type: str,
    title: str,
    body: str,
    metadata: dict,
) -> list[str]:
    """Create a notification for every leader on the project. Returns list of notif IDs."""
    activity.logger.info(
        "create_notifications_for_leadership: project=%s type=%s", project_id, notif_type
    )
    pool = get_pool()
    import json as _json

    async with pool.acquire() as conn:
        leaders = await conn.fetch(
            """
            SELECT person_id::TEXT FROM leadership WHERE project_id = $1::UUID
            """,
            project_id,
        )
        if not leaders:
            activity.logger.warning("No leaders found for project=%s", project_id)
            return []

        notif_ids: list[str] = []
        for leader in leaders:
            notif_id = await conn.fetchval(
                """
                INSERT INTO notification (event_id, recipient_id, type, title, body, metadata)
                VALUES ($1::UUID, $2::UUID, $3, $4, $5, $6::JSONB)
                RETURNING id::TEXT
                """,
                event_id if event_id else None,
                leader["person_id"],
                notif_type,
                title,
                body,
                _json.dumps(metadata),
            )
            notif_ids.append(notif_id)
            activity.logger.info(
                "Notification %s created for leader=%s", notif_id, leader["person_id"]
            )
        return notif_ids


# ---------------------------------------------------------------------------
# Activity: update_assignment_status
# ---------------------------------------------------------------------------
@activity.defn(name="update_assignment_status")
async def update_assignment_status(
    assignment_id: str, new_status: str, notes: str
) -> bool:
    """UPDATE assignment SET status=..., notes=..., updated_at=NOW()."""
    activity.logger.info(
        "update_assignment_status: assignment=%s status=%s", assignment_id, new_status
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE assignment
               SET status = $1, notes = $2, updated_at = NOW()
             WHERE id = $3::UUID
            """,
            new_status,
            notes,
            assignment_id,
        )
        updated = result.split()[-1] != "0"
        activity.logger.info(
            "update_assignment_status result: %s (updated=%s)", result, updated
        )
        return updated


# ---------------------------------------------------------------------------
# Activity: update_opportunity_status
# ---------------------------------------------------------------------------
@activity.defn(name="update_opportunity_status")
async def update_opportunity_status(opportunity_id: str, new_status: str) -> bool:
    """UPDATE opportunity SET status=..., updated_at=NOW()."""
    activity.logger.info(
        "update_opportunity_status: opportunity=%s status=%s", opportunity_id, new_status
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE opportunity
               SET status = $1, updated_at = NOW()
             WHERE id = $2::UUID
            """,
            new_status,
            opportunity_id,
        )
        updated = result.split()[-1] != "0"
        return updated


# ---------------------------------------------------------------------------
# Activity: mark_domain_event_processed
# ---------------------------------------------------------------------------
@activity.defn(name="mark_domain_event_processed")
async def mark_domain_event_processed(
    event_id: str, error: str | None = None
) -> None:
    """Set processed_at (and optionally processing_error) on a domain_event row."""
    activity.logger.info(
        "mark_domain_event_processed: event_id=%s error=%s", event_id, error
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE domain_event
               SET processed_at = NOW(), processing_error = $1
             WHERE id = $2::UUID
            """,
            error,
            event_id,
        )
