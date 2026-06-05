"""
SHACL preflight validation activities.

Orchestrates availability checking in Jena and SHACL shape validation
before an assignment is confirmed.

Activities:
  - validate_allocation_preflight — aggregated go/no-go check
"""
from __future__ import annotations

import logging
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)

# Band ordering for recommendation messages
BAND_ORDER = [
    "Analyst",
    "Consultant",
    "Senior Consultant",
    "Manager",
    "Senior Manager",
    "Director",
    "Partner",
]


# ---------------------------------------------------------------------------
# Activity: validate_allocation_preflight
# ---------------------------------------------------------------------------
@activity.defn(name="validate_allocation_preflight")
async def validate_allocation_preflight(
    person_id: str,
    opportunity_id: str,
    start_date: str,
    end_date: str,
    allocation_pct: float,
) -> dict[str, Any]:
    """
    Preflight check before committing an assignment.

    Calls:
      1. check_availability_in_jena  — detects date-overlap conflicts in Jena ABox
      2. run_preflight_shacl         — validates proposed triples against SHACL shapes

    Returns:
      {
        can_proceed: bool,
        violations: list[str],    # hard blockers
        warnings: list[str],      # soft flags
        recommendation: str,      # human-readable summary
      }
    """
    activity.logger.info(
        "validate_allocation_preflight: person=%s opp=%s %s→%s pct=%s%%",
        person_id,
        opportunity_id,
        start_date,
        end_date,
        allocation_pct,
    )

    # Import here to avoid circular imports and keep Temporal sandbox happy —
    # we call the activity functions directly (not via workflow.execute_activity)
    # because shacl_activities itself is an activity running inside the worker.
    from src.activities.sparql_activities import (  # noqa: PLC0415
        check_availability_in_jena,
        run_preflight_shacl,
    )
    from src.config import settings  # noqa: PLC0415

    STF = settings.STF_NAMESPACE
    violations: list[str] = []
    warnings_list: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Availability check in Jena
    # ------------------------------------------------------------------
    person_uri = f"{STF}person/{person_id}"
    avail_result = await check_availability_in_jena(person_uri, start_date, end_date)

    if not avail_result.get("available", True):
        total_pct = avail_result.get("total_allocated_pct", 0.0)
        conflicts = avail_result.get("conflicts", [])
        remaining = 100.0 - total_pct
        if total_pct + allocation_pct > 100.0:
            violations.append(
                f"Allocation cap exceeded: person already has {total_pct:.0f}% "
                f"allocated during {start_date}→{end_date}. "
                f"Adding {allocation_pct:.0f}% would exceed 100% "
                f"(only {remaining:.0f}% available)."
            )
        else:
            warnings_list.append(
                f"Person has existing allocations ({total_pct:.0f}%) during the "
                f"requested period. Conflicts: {len(conflicts)} allocation(s) in Jena ABox."
            )
    elif avail_result.get("total_allocated_pct", 0.0) > 0:
        warnings_list.append(
            f"Person has {avail_result['total_allocated_pct']:.0f}% existing allocation "
            f"during this period but is still within capacity."
        )

    # ------------------------------------------------------------------
    # Step 2: SHACL preflight on proposed triples
    # ------------------------------------------------------------------
    opportunity_uri = f"{STF}opportunity/{opportunity_id}"
    allocation_id_placeholder = f"temp-{person_id[:8]}-{opportunity_id[:8]}"
    allocation_uri = f"{STF}allocation/{allocation_id_placeholder}"

    turtle_fragment = (
        f"<{allocation_uri}> a <{STF}ProjectAllocation> ;\n"
        f"    <{STF}allocatedPerson>    <{person_uri}> ;\n"
        f"    <{STF}forOpportunity>     <{opportunity_uri}> ;\n"
        f'    <{STF}allocationStartDate> "{start_date}"^^<http://www.w3.org/2001/XMLSchema#date> ;\n'
        f'    <{STF}allocationEndDate>   "{end_date}"^^<http://www.w3.org/2001/XMLSchema#date> ;\n'
        f'    <{STF}allocationPercent>   "{allocation_pct}"^^<http://www.w3.org/2001/XMLSchema#decimal> .\n'
        f"<{person_uri}> <{STF}hasActiveAllocation> <{allocation_uri}> .\n"
    )

    shacl_result = await run_preflight_shacl(turtle_fragment)
    violations.extend(shacl_result.get("violations", []))
    warnings_list.extend(shacl_result.get("warnings", []))

    # ------------------------------------------------------------------
    # Build recommendation
    # ------------------------------------------------------------------
    can_proceed = len(violations) == 0

    if can_proceed and not warnings_list:
        recommendation = (
            f"All preflight checks passed. Person {person_id} can be assigned to "
            f"opportunity {opportunity_id} at {allocation_pct:.0f}% from {start_date} "
            f"to {end_date}."
        )
    elif can_proceed and warnings_list:
        recommendation = (
            f"Preflight checks passed with {len(warnings_list)} warning(s). "
            f"Review warnings before confirming the assignment."
        )
    else:
        recommendation = (
            f"Preflight checks FAILED with {len(violations)} violation(s). "
            f"This assignment cannot proceed until violations are resolved."
        )

    activity.logger.info(
        "validate_allocation_preflight: can_proceed=%s violations=%d warnings=%d",
        can_proceed,
        len(violations),
        len(warnings_list),
    )

    return {
        "can_proceed": can_proceed,
        "violations": violations,
        "warnings": warnings_list,
        "recommendation": recommendation,
    }
