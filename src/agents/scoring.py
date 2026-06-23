"""
Deterministic multi-factor candidate scorer — the AUDITABLE core of the agent.

This module is PURE: no LLM, no I/O. It operates on already-fetched data dicts
(assembled by ``src.agents.data_access``) so it can be unit-tested in isolation
and so that the exact same scoring runs in both the Temporal activity context
and the FastAPI request context.

Design principle: the LLM NEVER computes scores or invents candidates. Scoring
is a pure function of Postgres facts + SPARQL skill traversal. This preserves
auditability — every score is reproducible from the inputs.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Ordered vocabularies (index == rank)
# ---------------------------------------------------------------------------
BAND_HIERARCHY = [
    "Analyst",
    "Consultant",
    "Senior Consultant",
    "Manager",
    "Senior Manager",
    "Director",
    "Partner",
]

PROFICIENCY_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2, "expert": 3}

# Language proficiency: basic < professional < fluent < native
LANGUAGE_RANK = {"basic": 0, "professional": 1, "fluent": 2, "native": 3}

# Qualification level: bachelor < master < phd; professional treated as >= bachelor
QUAL_RANK = {"bachelor": 1, "professional": 1, "master": 2, "phd": 3}

# Roles considered "senior-ish" for role_category compatibility scoring.
_SENIOR_ROLES = {"manager", "lead", "architect", "expert", "specialist"}

# Default factor weights — MUST sum to 1.0.
DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 0.30,
    "industry_fit": 0.12,
    "role_category_fit": 0.08,
    "function_fit": 0.08,
    "location": 0.10,
    "experience": 0.10,
    "qualifications": 0.07,
    "certifications": 0.06,
    "language": 0.05,
    "availability_headroom": 0.04,
}

_UNAVAILABLE_STATUSES = {"on_leave", "inactive"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _band_rank(band: str | None) -> int:
    try:
        return BAND_HIERARCHY.index(band or "")
    except ValueError:
        return -1


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------
def _evaluate_gates(
    candidate: dict, requirement: dict, matched_skill_ids: set
) -> tuple[bool, list[str], list[str]]:
    """Return (gate_passed, gate_failures, missing_mandatory_skills)."""
    failures: list[str] = []
    missing_mandatory: list[str] = []

    # --- Band gate ---
    req_band = requirement.get("band_required")
    if req_band:
        if _band_rank(candidate.get("band")) < _band_rank(req_band):
            failures.append(
                f"band: {candidate.get('band')!r} < required {req_band!r}"
            )

    # --- Availability gate ---
    status = _norm(candidate.get("status"))
    phase = candidate.get("availability_phase") or ""
    requested = requirement.get("requested_allocation_pct")
    available_pct = float(candidate.get("available_pct") or 0)
    if status in _UNAVAILABLE_STATUSES:
        failures.append(f"availability: status is {status!r}")
    elif phase == "FullyAllocated":
        failures.append("availability: candidate is FullyAllocated")
    else:
        if requested is not None:
            if available_pct < float(requested):
                failures.append(
                    f"availability: available {available_pct:.0f}% < "
                    f"requested {float(requested):.0f}%"
                )
        elif available_pct <= 0:
            failures.append("availability: no headroom (available_pct=0)")

    # --- Mandatory skills gate ---
    for sk in requirement.get("mandatory_skills", []):
        sid = sk.get("skill_id")
        if sid is not None and sid not in matched_skill_ids:
            failures.append(f"skill: missing mandatory {sk.get('name') or sid!r}")
            missing_mandatory.append(sk.get("name") or str(sid))

    # --- Mandatory certifications gate ---
    valid_cert_names = {
        _norm(c.get("name")) for c in candidate.get("certifications", []) if c.get("is_valid")
    }
    for cert in requirement.get("mandatory_certs", []):
        if _norm(cert) not in valid_cert_names:
            failures.append(f"certification: missing valid {cert!r}")
            missing_mandatory.append(f"cert:{cert}")

    # --- Mandatory qualifications gate ---
    for req_q in requirement.get("mandatory_quals", []):
        req_level = QUAL_RANK.get(_norm(req_q.get("level")), 0)
        req_field = _norm(req_q.get("field"))
        ok = False
        for q in candidate.get("qualifications", []):
            cand_level = QUAL_RANK.get(_norm(q.get("level")), 0)
            if cand_level >= req_level and (
                not req_field or _norm(q.get("field_of_study")) == req_field
            ):
                ok = True
                break
        if not ok:
            label = req_q.get("level") or "qualification"
            if req_field:
                label = f"{label} in {req_q.get('field')}"
            failures.append(f"qualification: missing {label}")
            missing_mandatory.append(f"qual:{label}")

    # --- Mandatory languages gate ---
    for req_l in requirement.get("mandatory_languages", []):
        req_rank = LANGUAGE_RANK.get(_norm(req_l.get("min_prof")), 0)
        code = _norm(req_l.get("code"))
        ok = any(
            _norm(l.get("language_code")) == code
            and LANGUAGE_RANK.get(_norm(l.get("proficiency")), 0) >= req_rank
            for l in candidate.get("languages", [])
        )
        if not ok:
            failures.append(f"language: missing {req_l.get('code')!r} at required level")
            missing_mandatory.append(f"lang:{req_l.get('code')}")

    # --- Mandatory citizenships gate ---
    req_cits = requirement.get("mandatory_citizenships", [])
    if req_cits:
        held = {_norm(c) for c in candidate.get("citizenships", [])}
        if not any(_norm(c) in held for c in req_cits):
            failures.append(
                f"citizenship: holds none of {req_cits!r}"
            )
            missing_mandatory.append(f"citizenship:{'/'.join(req_cits)}")

    return (len(failures) == 0, failures, missing_mandatory)


# ---------------------------------------------------------------------------
# Factor sub-scores (each 0..1)
# ---------------------------------------------------------------------------
def _score_skills(
    candidate: dict, requirement: dict, matched_skill_ids: set
) -> tuple[float, list[str]]:
    mandatory = requirement.get("mandatory_skills", [])
    nice = requirement.get("nice_skills", [])
    num_mand = len(mandatory)
    num_nice = len(nice)

    if num_mand == 0 and num_nice == 0:
        return 1.0, []

    matched_names: list[str] = []
    matched_mand = 0
    for sk in mandatory:
        if sk.get("skill_id") in matched_skill_ids:
            matched_mand += 1
            matched_names.append(sk.get("name") or str(sk.get("skill_id")))
    matched_nice = 0
    for sk in nice:
        if sk.get("skill_id") in matched_skill_ids:
            matched_nice += 1
            matched_names.append(sk.get("name") or str(sk.get("skill_id")))

    denom = num_mand + 0.5 * num_nice
    base = (matched_mand + 0.5 * matched_nice) / denom if denom else 1.0

    # Proficiency bonus: reward advanced/expert proficiency on matched skills.
    required_ids = {sk.get("skill_id") for sk in mandatory + nice}
    high_prof = 0
    for s in candidate.get("skills", []):
        if s.get("skill_id") in required_ids and _norm(s.get("proficiency_level")) in (
            "advanced",
            "expert",
        ):
            high_prof += 1
    bonus = 0.05 * high_prof
    return _clamp(base + bonus), matched_names


def _score_industry_fit(candidate: dict, requirement: dict) -> float:
    industry = _norm(requirement.get("industry"))
    if not industry:
        return 0.7
    exposure = {_norm(i) for i in candidate.get("industry_exposure", [])}
    domain = {_norm(d) for d in candidate.get("domain_skills", [])}
    if industry in exposure or any(industry in d or d in industry for d in domain):
        return 1.0
    # Adjacent: token overlap with any exposure / domain skill.
    tokens = set(industry.split())
    for blob in exposure | domain:
        if tokens & set(blob.split()):
            return 0.5
    return 0.2


def _score_function_fit(candidate: dict, requirement: dict) -> float:
    function = _norm(requirement.get("function"))
    if not function:
        return 0.4
    func_tokens = set(function.split())
    for s in candidate.get("skills", []):
        if _norm(s.get("skill_type")) == "functional":
            if func_tokens & set(_norm(s.get("skill_name")).split()):
                return 1.0
    # Role alignment fallback.
    if func_tokens & set(_norm(candidate.get("role_category")).split()):
        return 1.0
    return 0.4


def _score_role_category_fit(candidate: dict, requirement: dict) -> float:
    req_rc = _norm(requirement.get("role_category"))
    cand_rc = _norm(candidate.get("role_category"))
    if not req_rc:
        return 0.7
    if req_rc == cand_rc:
        return 1.0
    if req_rc in _SENIOR_ROLES and cand_rc in _SENIOR_ROLES:
        return 0.5
    return 0.3


def _score_location(candidate: dict, requirement: dict) -> float:
    req_region = requirement.get("region")
    if not req_region:
        return 0.7
    req_office = _norm(requirement.get("office"))
    if req_office and _norm(candidate.get("office")) == req_office:
        return 1.0
    if _norm(candidate.get("region")) == _norm(req_region):
        return 0.6
    return 0.2


def _score_experience(candidate: dict) -> float:
    total = float(candidate.get("total_experience_months") or 0)
    in_role = float(candidate.get("experience_in_role_months") or 0)
    return _clamp(min(1.0, total / 180.0) * 0.6 + min(1.0, in_role / 48.0) * 0.4)


def _score_qualifications(candidate: dict, requirement: dict) -> float:
    required = requirement.get("mandatory_quals", [])
    if not required:
        return 1.0
    full = 0
    partial = 0
    for req_q in required:
        req_level = QUAL_RANK.get(_norm(req_q.get("level")), 0)
        req_field = _norm(req_q.get("field"))
        best = 0.0
        for q in candidate.get("qualifications", []):
            cand_level = QUAL_RANK.get(_norm(q.get("level")), 0)
            if cand_level >= req_level:
                if not req_field or _norm(q.get("field_of_study")) == req_field:
                    best = 1.0
                    break
                best = max(best, 0.5)  # level ok, field mismatch
        if best >= 1.0:
            full += 1
        elif best > 0:
            partial += 1
    return (full + 0.5 * partial) / len(required)


def _score_certifications(candidate: dict, requirement: dict) -> float:
    required = list(requirement.get("mandatory_certs", [])) + list(
        requirement.get("nice_certs", [])
    )
    if not required:
        return 1.0
    valid = {_norm(c.get("name")) for c in candidate.get("certifications", []) if c.get("is_valid")}
    held = sum(1 for c in required if _norm(c) in valid)
    return held / len(required)


def _score_language(candidate: dict, requirement: dict) -> float:
    nice = requirement.get("nice_languages", [])
    if not nice:
        return 1.0
    matched = 0
    for req_l in nice:
        req_rank = LANGUAGE_RANK.get(_norm(req_l.get("min_prof")), 0)
        code = _norm(req_l.get("code"))
        if any(
            _norm(l.get("language_code")) == code
            and LANGUAGE_RANK.get(_norm(l.get("proficiency")), 0) >= req_rank
            for l in candidate.get("languages", [])
        ):
            matched += 1
    return matched / len(nice)


def _score_availability_headroom(candidate: dict) -> float:
    return _clamp(float(candidate.get("available_pct") or 0) / 100.0)


# ---------------------------------------------------------------------------
# Public scoring entrypoints
# ---------------------------------------------------------------------------
def score_candidate(candidate: dict, requirement: dict, weights: dict) -> dict:
    """Compute the full multi-factor score for one candidate against one requirement.

    Pure function. ``candidate.matched_skill_ids`` (a set, already including
    SKOS-transitive matches) drives the skill gate + factor.
    """
    matched_skill_ids = candidate.get("matched_skill_ids") or set()
    if not isinstance(matched_skill_ids, set):
        matched_skill_ids = set(matched_skill_ids)

    gate_passed, gate_failures, missing_mandatory = _evaluate_gates(
        candidate, requirement, matched_skill_ids
    )

    skills_score, matched_skills = _score_skills(candidate, requirement, matched_skill_ids)

    factor_scores: dict[str, float] = {
        "skills": skills_score,
        "industry_fit": _score_industry_fit(candidate, requirement),
        "role_category_fit": _score_role_category_fit(candidate, requirement),
        "function_fit": _score_function_fit(candidate, requirement),
        "location": _score_location(candidate, requirement),
        "experience": _score_experience(candidate),
        "qualifications": _score_qualifications(candidate, requirement),
        "certifications": _score_certifications(candidate, requirement),
        "language": _score_language(candidate, requirement),
        "availability_headroom": _score_availability_headroom(candidate),
    }

    overall = sum(weights.get(f, 0.0) * s for f, s in factor_scores.items())
    overall_score = round(100.0 * overall, 1)

    return {
        "person_id": candidate.get("person_id"),
        "name": candidate.get("name"),
        "band": candidate.get("band"),
        "region": candidate.get("region"),
        "role_category": candidate.get("role_category"),
        "overall_score": overall_score,
        "gate_passed": gate_passed,
        "gate_failures": gate_failures,
        "factor_scores": {k: round(v, 3) for k, v in factor_scores.items()},
        "matched_skills": matched_skills,
        "missing_mandatory": missing_mandatory,
    }


def rank_candidates(
    candidates: list[dict], requirement: dict, weights: dict | None = None
) -> list[dict]:
    """Score every candidate and sort by (gate_passed desc, overall_score desc)."""
    w = weights or DEFAULT_WEIGHTS
    scored = [score_candidate(c, requirement, w) for c in candidates]
    scored.sort(key=lambda r: (r["gate_passed"], r["overall_score"]), reverse=True)
    return scored
