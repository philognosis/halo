"""
Notification composition activities for the Staffing System.

These activities build the human-readable content (title, body, metadata)
for notifications. They are pure functions — no I/O, no database calls.
The actual insertion of notification rows is done by db_activities.

Activities:
  - compose_team_nudge             — nudge leadership to create team
  - compose_candidate_recommendation — summarise top candidates
  - compose_approval_request       — HITL approval gate content
"""
from __future__ import annotations

import logging
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activity: compose_team_nudge
# ---------------------------------------------------------------------------
@activity.defn(name="compose_team_nudge")
async def compose_team_nudge(project: dict[str, Any]) -> dict[str, Any]:
    """
    Compose notification content nudging leadership to define the team structure
    for a newly created (or activated) project.

    Returns {title, body, metadata}.
    """
    activity.logger.info(
        "compose_team_nudge: project_id=%s", project.get("id", "unknown")
    )

    project_name = project.get("project_name", "Unnamed Project")
    client = project.get("client", "Unknown Client")
    start_date = project.get("start_date", "TBD")
    unique_code = project.get("unique_code", "")
    status = project.get("status", "pipeline")
    end_date = project.get("end_date") or "open-ended"

    title = f"Action Required: Define team structure for {project_name}"

    body = (
        f"A {'new' if status in ('pipeline', 'active') else ''} project has been registered "
        f"and requires a team to be defined before staffing can begin.\n\n"
        f"Project: {project_name} ({unique_code})\n"
        f"Client: {client}\n"
        f"Start Date: {start_date}\n"
        f"End Date: {end_date}\n\n"
        f"Please log in to the Staffing Portal and create the team structure, "
        f"including defining open opportunities (roles) so that the staffing agent "
        f"can begin sourcing candidates.\n\n"
        f"This request will escalate automatically after 72 hours if no team has been created."
    )

    metadata: dict[str, Any] = {
        "project_id": project.get("id"),
        "project_name": project_name,
        "client": client,
        "unique_code": unique_code,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "action": "create_team",
        "teams_count": len(project.get("teams", [])),
    }

    return {"title": title, "body": body, "metadata": metadata}


# ---------------------------------------------------------------------------
# Activity: compose_candidate_recommendation
# ---------------------------------------------------------------------------
@activity.defn(name="compose_candidate_recommendation")
async def compose_candidate_recommendation(
    opportunity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compose a candidate recommendation notification summarising the top 3 candidates
    for an open opportunity.

    Returns {title, body, metadata}.
    """
    activity.logger.info(
        "compose_candidate_recommendation: opportunity_id=%s candidates=%d",
        opportunity.get("id", "unknown"),
        len(candidates),
    )

    role_title = opportunity.get("role_title", "Open Role")
    band = opportunity.get("band_required", "")
    start_date = opportunity.get("start_date", "TBD")
    end_date = opportunity.get("end_date") or "open-ended"
    opp_id = opportunity.get("id", "")

    top_candidates = candidates[:3]
    candidate_count = len(candidates)

    title = f"Candidate Recommendation: {role_title} ({band})"

    if not top_candidates:
        body = (
            f"The staffing agent searched for candidates for the role of {role_title} "
            f"({band}) starting {start_date}, but no suitable candidates were found "
            f"in the current talent pool.\n\n"
            f"Please review the opportunity requirements or consider external sourcing."
        )
    else:
        candidate_lines: list[str] = []
        for i, cand in enumerate(top_candidates, start=1):
            name = cand.get("name", "Unknown")
            cand_band = cand.get("band", "")
            region = cand.get("region", "")
            availability = cand.get("availability_phase", "Unknown")
            matched_skills = cand.get("matched_skills", cand.get("score", 0))
            uri = cand.get("person_uri", "")

            candidate_lines.append(
                f"  {i}. {name} — {cand_band}, {region}\n"
                f"     Availability: {availability} | "
                f"Matched Skills: {matched_skills}\n"
                f"     Profile: {uri}"
            )

        candidates_text = "\n".join(candidate_lines)
        body = (
            f"The staffing agent has identified {candidate_count} candidate(s) "
            f"for the role of {role_title} ({band}).\n\n"
            f"Opportunity Details:\n"
            f"  Start Date: {start_date}  |  End Date: {end_date}\n\n"
            f"Top Candidates:\n{candidates_text}\n\n"
            f"Please review and approve or reject candidates in the Staffing Portal. "
            f"This recommendation will expire in 7 days without action."
        )

    metadata: dict[str, Any] = {
        "opportunity_id": opp_id,
        "role_title": role_title,
        "band_required": band,
        "start_date": start_date,
        "end_date": end_date,
        "candidate_count": candidate_count,
        "top_candidates": [
            {
                "person_uri": c.get("person_uri", ""),
                "name": c.get("name", ""),
                "band": c.get("band", ""),
                "region": c.get("region", ""),
                "availability_phase": c.get("availability_phase", ""),
                "matched_skills": c.get("matched_skills", c.get("score", 0)),
            }
            for c in top_candidates
        ],
        "action": "review_candidates",
    }

    return {"title": title, "body": body, "metadata": metadata}


# ---------------------------------------------------------------------------
# Activity: compose_approval_request
# ---------------------------------------------------------------------------
@activity.defn(name="compose_approval_request")
async def compose_approval_request(
    assignment: dict[str, Any],
    opportunity: dict[str, Any],
    person: dict[str, Any],
) -> dict[str, Any]:
    """
    Compose an approval request notification for a proposed assignment.

    Includes person name, band, matched skills, allocation %, and dates.
    Returns {title, body, metadata}.
    """
    activity.logger.info(
        "compose_approval_request: assignment_id=%s", assignment.get("id", "unknown")
    )

    assignment_id = assignment.get("id", "")
    person_name = person.get("name", assignment.get("person_name", "Unknown"))
    person_band = person.get("band", assignment.get("person_band", ""))
    person_region = person.get("region", assignment.get("person_region", ""))
    person_email = person.get("email", assignment.get("person_email", ""))

    role_title = opportunity.get("role_title", assignment.get("role_title", "Open Role"))
    required_band = opportunity.get("band_required", assignment.get("band_required", ""))
    required_skills = opportunity.get("required_skills", [])

    start_date = assignment.get("start_date", opportunity.get("start_date", "TBD"))
    end_date = assignment.get("end_date") or opportunity.get("end_date") or "open-ended"
    allocation_pct = assignment.get("allocation_pct", 100)

    # Build skill summary
    mandatory_skills = [s["skill_name"] for s in required_skills if s.get("is_mandatory")]
    optional_skills = [s["skill_name"] for s in required_skills if not s.get("is_mandatory")]

    skill_lines = ""
    if mandatory_skills:
        skill_lines += f"  Mandatory: {', '.join(mandatory_skills)}\n"
    if optional_skills:
        skill_lines += f"  Optional:  {', '.join(optional_skills)}\n"
    if not skill_lines:
        skill_lines = "  (none specified)\n"

    title = f"Approval Required: {person_name} → {role_title}"

    body = (
        f"A staffing assignment requires your approval before it can be confirmed.\n\n"
        f"Candidate:\n"
        f"  Name:       {person_name}\n"
        f"  Email:      {person_email}\n"
        f"  Band:       {person_band} (required: {required_band})\n"
        f"  Region:     {person_region}\n\n"
        f"Role: {role_title}\n"
        f"  Allocation: {allocation_pct}%\n"
        f"  Start Date: {start_date}\n"
        f"  End Date:   {end_date}\n\n"
        f"Required Skills:\n{skill_lines}\n"
        f"Please log in to the Staffing Portal to approve or reject this assignment. "
        f"This request will escalate after 5 days without a decision."
    )

    metadata: dict[str, Any] = {
        "assignment_id": assignment_id,
        "person_id": assignment.get("person_id", person.get("id", "")),
        "person_name": person_name,
        "person_band": person_band,
        "person_region": person_region,
        "opportunity_id": assignment.get("opportunity_id", opportunity.get("id", "")),
        "role_title": role_title,
        "band_required": required_band,
        "allocation_pct": allocation_pct,
        "start_date": start_date,
        "end_date": end_date,
        "mandatory_skills": mandatory_skills,
        "action": "approve_or_reject_assignment",
    }

    return {"title": title, "body": body, "metadata": metadata}
