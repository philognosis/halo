"""
Postgres → Jena ABox projection.

This module reads the operational store (PostgreSQL) and generates Turtle
triples that represent the current state of the semantic graph (the ABox).
It is the bridge that keeps Jena in sync with the source of truth.

The projection is intentionally free of Temporal imports so it can run inside
the FastAPI process (via the periodic sync loop and the /admin/sync-abox
endpoint).

URI conventions (must match the worker activities in sparql_activities.py /
shacl_activities.py):
  - person      : {stf_ns}person/{person_id}
  - allocation  : {stf_ns}allocation/{assignment_id}
  - opportunity : {stf_ns}opportunity/{opportunity_id}

Availability phase strings from the person_availability view are mapped to
the gUFO Phase classes in the ontology:
  Available | PartiallyAllocated | FullyAllocated | OnLeave
(Inactive persons are projected with no phase instance.)
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from src.config import settings

logger = logging.getLogger(__name__)

ABOX_GRAPH_URI = "http://enterprise.org/graphs/abox"

XSD = "http://www.w3.org/2001/XMLSchema#"

# Map of person_availability.availability_phase → stf phase class local name.
_PHASE_CLASS = {
    "Available": "Available",
    "PartiallyAllocated": "PartiallyAllocated",
    "FullyAllocated": "FullyAllocated",
    "OnLeave": "OnLeave",
}


def _esc(value: str) -> str:
    """Escape a string for safe inclusion in a Turtle double-quoted literal."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _lit(value: Any) -> str:
    """A plain xsd:string literal."""
    return f'"{_esc(str(value))}"^^<{XSD}string>'


def _date_lit(value: str) -> str:
    return f'"{_esc(value)}"^^<{XSD}date>'


def _dec_lit(value: Any) -> str:
    return f'"{value}"^^<{XSD}decimal>'


async def build_abox_turtle(pool: asyncpg.Pool) -> str:
    """
    Query Postgres and build the full ABox as a Turtle string (a flat list of
    triples — no @prefix declarations, so it can be embedded directly inside an
    ``INSERT DATA { GRAPH <abox> { ... } }`` clause).
    """
    stf = settings.STF_NAMESPACE
    lines: list[str] = []

    async with pool.acquire() as conn:
        persons = await conn.fetch(
            """
            SELECT
                pa.person_id::TEXT          AS person_id,
                pa.name,
                pa.band,
                pa.region,
                pa.office,
                pa.person_status,
                pa.availability_phase
            FROM person_availability pa
            ORDER BY pa.person_id
            """
        )
        skills = await conn.fetch(
            """
            SELECT s.person_id::TEXT AS person_id, s.skill_id
            FROM skills s
            WHERE s.skill_id IS NOT NULL AND s.skill_id <> ''
            ORDER BY s.person_id
            """
        )
        allocations = await conn.fetch(
            """
            SELECT
                a.id::TEXT          AS assignment_id,
                a.person_id::TEXT   AS person_id,
                a.opportunity_id::TEXT AS opportunity_id,
                a.start_date::TEXT  AS start_date,
                a.end_date::TEXT    AS end_date,
                a.allocation_pct,
                a.status
            FROM assignment a
            WHERE a.status IN ('staffed', 'short_listed')
            ORDER BY a.id
            """
        )
        opportunities = await conn.fetch(
            """
            SELECT
                o.id::TEXT          AS opportunity_id,
                o.band_required,
                o.status
            FROM opportunity o
            ORDER BY o.id
            """
        )

    # ----- Persons -----
    person_count = len(persons)
    for p in persons:
        p_uri = f"{stf}person/{p['person_id']}"
        lines.append(f"<{p_uri}> a <{stf}Person>, <{stf}Employee> .")
        lines.append(f"<{p_uri}> <{stf}hasName> {_lit(p['name'])} .")
        if p["band"]:
            lines.append(f"<{p_uri}> <{stf}hasBand> {_lit(p['band'])} .")
        if p["region"]:
            lines.append(f"<{p_uri}> <{stf}hasRegion> {_lit(p['region'])} .")
        if p["office"]:
            lines.append(f"<{p_uri}> <{stf}hasOffice> {_lit(p['office'])} .")
        phase_cls = _PHASE_CLASS.get(p["availability_phase"])
        if phase_cls:
            lines.append(
                f"<{p_uri}> <{stf}hasAvailabilityPhase> <{stf}{phase_cls}> ."
            )

    # ----- Skills (person → SKOS concept) -----
    for s in skills:
        p_uri = f"{stf}person/{s['person_id']}"
        concept_uri = f"{stf}{s['skill_id']}"
        lines.append(f"<{p_uri}> <{stf}hasSkill> <{concept_uri}> .")

    # ----- Allocations -----
    allocation_count = len(allocations)
    for a in allocations:
        alloc_uri = f"{stf}allocation/{a['assignment_id']}"
        p_uri = f"{stf}person/{a['person_id']}"
        opp_uri = f"{stf}opportunity/{a['opportunity_id']}"
        lines.append(f"<{alloc_uri}> a <{stf}ProjectAllocation> .")
        lines.append(f"<{alloc_uri}> <{stf}allocatedEmployee> <{p_uri}> .")
        lines.append(f"<{alloc_uri}> <{stf}allocatedToOpportunity> <{opp_uri}> .")
        if a["start_date"]:
            lines.append(
                f"<{alloc_uri}> <{stf}allocationStart> {_date_lit(a['start_date'])} ."
            )
        if a["end_date"]:
            lines.append(
                f"<{alloc_uri}> <{stf}allocationEnd> {_date_lit(a['end_date'])} ."
            )
        lines.append(
            f"<{alloc_uri}> <{stf}allocationPct> {_dec_lit(a['allocation_pct'])} ."
        )
        lines.append(f"<{p_uri}> <{stf}hasActiveAllocation> <{alloc_uri}> .")

    # ----- Opportunities -----
    for o in opportunities:
        opp_uri = f"{stf}opportunity/{o['opportunity_id']}"
        lines.append(f"<{opp_uri}> a <{stf}Opportunity> .")
        if o["band_required"]:
            lines.append(
                f"<{opp_uri}> <{stf}requiredBand> {_lit(o['band_required'])} ."
            )
        if o["status"]:
            lines.append(
                f"<{opp_uri}> <{stf}opportunityStatus> {_lit(o['status'])} ."
            )

    turtle = "\n".join(lines)
    logger.debug(
        "build_abox_turtle: persons=%d allocations=%d triples~=%d",
        person_count,
        allocation_count,
        len(lines),
    )
    return turtle


async def sync_abox(
    pool: asyncpg.Pool,
    sparql_client: Any,
    abox_graph_uri: str = ABOX_GRAPH_URI,
) -> dict[str, Any]:
    """
    Build the ABox Turtle from Postgres and atomically replace the named graph
    in Jena: DROP SILENT GRAPH <abox> ; INSERT DATA { GRAPH <abox> { ... } }.

    Returns a result dict with counts.
    """
    turtle = await build_abox_turtle(pool)
    triple_estimate = sum(
        1 for line in turtle.splitlines() if line.rstrip().endswith(".")
    )

    # Count persons / allocations cheaply for the report.
    persons = turtle.count(f"a <{settings.STF_NAMESPACE}Person>")
    allocations = turtle.count(f"a <{settings.STF_NAMESPACE}ProjectAllocation>")

    drop_ok = await sparql_client.update(f"DROP SILENT GRAPH <{abox_graph_uri}>")

    insert_ok = True
    if turtle.strip():
        insert_query = (
            f"INSERT DATA {{ GRAPH <{abox_graph_uri}> {{ {turtle} }} }}"
        )
        insert_ok = await sparql_client.update(insert_query)

    synced = bool(drop_ok and insert_ok)
    logger.info(
        "sync_abox: synced=%s persons=%d allocations=%d triples~=%d",
        synced,
        persons,
        allocations,
        triple_estimate,
    )
    return {
        "synced": synced,
        "triple_estimate": triple_estimate,
        "persons": persons,
        "allocations": allocations,
    }
