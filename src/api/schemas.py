"""
Pydantic v2 request/response models for the Staffing System API.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_BANDS = (
    "Analyst",
    "Consultant",
    "Senior Consultant",
    "Manager",
    "Senior Manager",
    "Director",
    "Partner",
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approver_id: str
    notes: str = ""


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approver_id: str
    reason: str


class CandidateApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approver_id: str


class CandidateRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unique_code: str
    client: str
    project_name: str
    start_date: date
    end_date: date | None = None
    industry: str
    sector: str
    function: str
    region: str = "EMEA"
    status: str = "active"


class CreateTeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    team_lead_id: str | None = None


class RequiredSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str | None = None
    skill_name: str
    skill_type: str
    min_proficiency: str | None = None
    is_mandatory: bool = True


class RequiredQualification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qualification_level: str
    field_of_study: str | None = None
    is_mandatory: bool = True


class CreateOpportunityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: str
    role_title: str
    description: str | None = None
    band_required: str
    start_date: date
    end_date: date | None = None
    required_skills: list[RequiredSkill] = Field(default_factory=list)
    required_qualifications: list[RequiredQualification] = Field(default_factory=list)


class CreateShortlistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opportunity_id: str
    person_id: str
    start_date: date
    end_date: date | None = None
    allocation_pct: float = 100
    assigned_by: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class PersonSummary(BaseModel):
    id: str
    name: str
    band: str | None = None
    region: str | None = None
    office: str | None = None
    status: str | None = None


class PersonAvailability(BaseModel):
    person_id: str
    name: str
    band: str | None = None
    region: str | None = None
    office: str | None = None
    person_status: str | None = None
    allocated_pct: float | None = None
    available_pct: float | None = None
    active_assignment_count: int | None = None
    availability_phase: str | None = None
    next_available_date: str | None = None
    assignment_statuses: list[str] = Field(default_factory=list)
    active_assignments: list[dict[str, Any]] = Field(default_factory=list)


class CandidateMatch(BaseModel):
    person_uri: str
    person_id: str | None = None
    name: str
    band: str | None = None
    region: str | None = None
    availability_phase: str | None = None
    matched_skills: int = 0
    score: int = 0


class CandidateSearchResult(BaseModel):
    opportunity_id: str
    source: str  # "jena" | "postgres_fallback"
    count: int
    candidates: list[CandidateMatch] = Field(default_factory=list)


class NotificationOut(BaseModel):
    id: str
    event_id: str | None = None
    recipient_id: str
    type: str
    title: str
    body: str
    metadata: dict[str, Any] | None = None
    is_read: bool
    read_at: str | None = None
    created_at: str | None = None
    expires_at: str | None = None


class AssignmentOut(BaseModel):
    id: str
    opportunity_id: str
    person_id: str
    start_date: str | None = None
    end_date: str | None = None
    allocation_pct: float | None = None
    status: str
    notes: str | None = None
    assigned_by: str | None = None
    assigned_at: str | None = None
    # denormalised person + opportunity fields (present on detail view)
    person_name: str | None = None
    person_band: str | None = None
    role_title: str | None = None
    band_required: str | None = None
    project_id: str | None = None


class ProjectOut(BaseModel):
    id: str
    unique_code: str
    client: str
    project_name: str
    start_date: str | None = None
    end_date: str | None = None
    industry: str | None = None
    sector: str | None = None
    function: str | None = None
    status: str
    leadership: list[dict[str, Any]] = Field(default_factory=list)
    teams: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowStatusOut(BaseModel):
    workflow_id: str
    decision: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    db_status: str | None = None


# ---------------------------------------------------------------------------
# Create acknowledgements (return the auto-started workflow id)
# ---------------------------------------------------------------------------
class CreateProjectResponse(BaseModel):
    project_id: str
    workflow_id: str


class CreateTeamResponse(BaseModel):
    team_id: str
    workflow_id: str


class CreateOpportunityResponse(BaseModel):
    opportunity_id: str


class CreateShortlistResponse(BaseModel):
    assignment_id: str
    workflow_id: str
    status: str


class SignalResponse(BaseModel):
    signaled: bool
    workflow_id: str
