"""
LangGraph multi-agent pipeline for resolving staffing conflicts.

Nodes:
  1. detect             -- deterministic conflict detection (overallocation,
                           double-booking, band mismatch, cert expired, on-leave)
  2. find_alternatives  -- fetch alternative candidates from DB when conflicts exist
  3. resolve            -- propose concrete alternatives for each conflict
  4. mediate            -- select best resolution per conflict, produce recommendation

The LLM (Anthropic AsyncAnthropic) enriches each stage when an API key is
available. Every node has a deterministic fallback so the pipeline works without
LLM access -- the LLM adds nuance, not correctness.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import date, datetime
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.data_access import (
    enrich_candidates,
    fetch_candidate_pool,
)
from src.agents.scoring import (
    BAND_HIERARCHY,
    DEFAULT_WEIGHTS,
    rank_candidates,
    _band_rank,
)
from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class ConflictResolutionState(TypedDict, total=False):
    assignment: dict                     # proposed assignment details
    person: dict                         # person profile with availability
    opportunity: dict                    # opportunity requirements
    conflicts: list                      # detected conflicts
    resolutions: list                    # proposed resolutions per conflict
    recommendation: Optional[dict]       # mediator's final recommendation
    alternative_candidates: list         # substitute candidates if needed
    messages: list                       # agent-to-agent audit log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_HARD_BLOCK_TYPES = {"overallocation", "on_leave"}


def _dates_overlap(
    start_a: date | str | None,
    end_a: date | str | None,
    start_b: date | str | None,
    end_b: date | str | None,
) -> bool:
    """Return True if [start_a, end_a] and [start_b, end_b] overlap."""
    def _to_date(v: date | str | None) -> date:
        if v is None:
            return date(9999, 12, 31)
        if isinstance(v, str):
            return datetime.strptime(v, "%Y-%m-%d").date()
        return v

    sa, ea = _to_date(start_a), _to_date(end_a)
    sb, eb = _to_date(start_b), _to_date(end_b)
    return sa <= eb and sb <= ea


def _to_date_or_none(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _log_message(messages: list, agent: str, text: str) -> None:
    """Append a timestamped audit entry to the message log."""
    messages.append({
        "agent": agent,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "text": text,
    })


def _parse_json_from_text(text: str) -> dict | None:
    """Extract first JSON object from LLM response text."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return _json.loads(text[start:end])
    except (ValueError, _json.JSONDecodeError):
        return None


async def _llm_call(system: str, user: str) -> str | None:
    """Call the Anthropic API. Returns the text response or None on failure."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else str(block)
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Node 1: Detect
# ---------------------------------------------------------------------------
async def _detect(state: ConflictResolutionState) -> dict:
    assignment = state.get("assignment") or {}
    person = state.get("person") or {}
    opportunity = state.get("opportunity") or {}
    messages: list = list(state.get("messages") or [])
    conflicts: list[dict] = []

    alloc_pct = float(assignment.get("allocation_pct", 100))

    # -- Overallocation --
    person_allocated_pct = float(person.get("allocated_pct", 0))
    if person_allocated_pct + alloc_pct > 100:
        conflicts.append({
            "type": "overallocation",
            "severity": "hard_block",
            "description": (
                f"Adding {alloc_pct:.0f}% to current "
                f"{person_allocated_pct:.0f}% exceeds 100%"
            ),
            "details": {
                "current_allocation_pct": person_allocated_pct,
                "requested_allocation_pct": alloc_pct,
                "total_if_approved": person_allocated_pct + alloc_pct,
            },
        })

    # -- Double-booking (date overlap with active assignments) --
    active_assignments = person.get("active_assignments") or []
    assign_start = assignment.get("start_date")
    assign_end = assignment.get("end_date")
    assign_opp_id = assignment.get("opportunity_id")

    for existing in active_assignments:
        # Parse JSONB dict from person_availability view
        ex = existing if isinstance(existing, dict) else {}
        ex_opp_id = str(ex.get("opportunity_id", ""))
        # Skip self-comparison
        if ex_opp_id and ex_opp_id == str(assign_opp_id or ""):
            continue
        if _dates_overlap(
            assign_start, assign_end,
            ex.get("start_date"), ex.get("end_date"),
        ):
            conflicts.append({
                "type": "double_booking",
                "severity": "soft_warning",
                "description": (
                    f"Overlaps with opportunity {ex_opp_id} "
                    f"({ex.get('start_date')} - {ex.get('end_date')})"
                ),
                "details": {
                    "existing_opportunity_id": ex_opp_id,
                    "existing_start_date": ex.get("start_date"),
                    "existing_end_date": ex.get("end_date"),
                    "existing_allocation_pct": ex.get("allocation_pct"),
                },
            })

    # -- Band mismatch --
    band_required = opportunity.get("band_required")
    person_band = person.get("band")
    if band_required and person_band:
        if _band_rank(person_band) < _band_rank(band_required):
            conflicts.append({
                "type": "band_mismatch",
                "severity": "soft_warning",
                "description": (
                    f"Person band {person_band} < "
                    f"required {band_required}"
                ),
                "details": {
                    "person_band": person_band,
                    "required_band": band_required,
                    "person_band_rank": _band_rank(person_band),
                    "required_band_rank": _band_rank(band_required),
                },
            })

    # -- On-leave --
    person_status = (person.get("status") or person.get("person_status") or "").lower()
    if person_status == "on_leave":
        conflicts.append({
            "type": "on_leave",
            "severity": "hard_block",
            "description": "Person is currently on leave",
            "details": {
                "person_status": person_status,
                "next_available_date": person.get("next_available_date"),
            },
        })

    # -- Expired certifications --
    required_certs = opportunity.get("mandatory_certs") or []
    person_certs = person.get("certifications") or []
    person_cert_map: dict[str, dict] = {}
    for pc in person_certs:
        cert_name = (pc.get("name") or "").strip().lower()
        if cert_name:
            person_cert_map[cert_name] = pc

    for req_cert in required_certs:
        norm_name = req_cert.strip().lower() if isinstance(req_cert, str) else ""
        matched_cert = person_cert_map.get(norm_name)
        if matched_cert and not matched_cert.get("is_valid", True):
            conflicts.append({
                "type": "cert_expired",
                "severity": "soft_warning",
                "description": f"Required certification '{req_cert}' has expired",
                "details": {
                    "certification": req_cert,
                    "expiry_date": matched_cert.get("expiry_date"),
                },
            })

    _log_message(
        messages, "detector",
        f"Detected {len(conflicts)} conflict(s): "
        + ", ".join(c["type"] for c in conflicts) if conflicts
        else "No conflicts detected",
    )

    # -- Optional LLM enrichment --
    if conflicts and settings.ANTHROPIC_API_KEY:
        system = (
            "You are a staffing conflict detector. Analyze a proposed assignment "
            "and identify ALL conflicts: overallocation, scheduling overlaps, band "
            "mismatches, certification issues, leave conflicts. Be thorough -- "
            "missed conflicts cause operational failures. Output JSON: {conflicts: "
            "[{type, severity: 'hard_block'|'soft_warning', description, details}]}."
        )
        user_payload = _json.dumps({
            "assignment": assignment,
            "person_summary": {
                "name": person.get("name"),
                "band": person.get("band"),
                "status": person_status,
                "allocated_pct": person_allocated_pct,
                "active_assignments": active_assignments,
                "certifications": person_certs,
            },
            "opportunity_summary": {
                "band_required": band_required,
                "mandatory_certs": required_certs,
            },
            "deterministic_conflicts": conflicts,
        }, default=str)
        llm_text = await _llm_call(system, user_payload)
        if llm_text:
            parsed = _parse_json_from_text(llm_text)
            if parsed and isinstance(parsed.get("conflicts"), list):
                # Merge LLM-found conflicts that are new types
                existing_keys = {
                    (c["type"], c.get("description", "")) for c in conflicts
                }
                for llm_c in parsed["conflicts"]:
                    key = (llm_c.get("type", ""), llm_c.get("description", ""))
                    if key not in existing_keys:
                        llm_c.setdefault("severity", "soft_warning")
                        conflicts.append(llm_c)
                        existing_keys.add(key)
                _log_message(
                    messages, "detector",
                    f"LLM enrichment added {len(parsed['conflicts'])} conflict(s)",
                )

    return {"conflicts": conflicts, "messages": messages}


# ---------------------------------------------------------------------------
# Node 2: Find alternatives
# ---------------------------------------------------------------------------
def _build_find_alternatives(pool: Any):
    async def find_alternatives(state: ConflictResolutionState) -> dict:
        conflicts = state.get("conflicts") or []
        opportunity = state.get("opportunity") or {}
        person = state.get("person") or {}
        messages: list = list(state.get("messages") or [])
        alternative_candidates: list[dict] = []

        if not conflicts:
            _log_message(messages, "find_alternatives", "No conflicts; skipping.")
            return {"alternative_candidates": [], "messages": messages}

        try:
            region = opportunity.get("region")
            band_required = opportunity.get("band_required") or "Analyst"
            candidates = await fetch_candidate_pool(pool, region, band_required)
            await enrich_candidates(pool, candidates)

            # Exclude the person who has the conflict
            person_id = person.get("person_id") or person.get("id")
            if person_id:
                candidates = [
                    c for c in candidates
                    if str(c.get("person_id")) != str(person_id)
                ]

            # Score and rank against the opportunity (treated as requirement)
            ranked = rank_candidates(candidates, opportunity, DEFAULT_WEIGHTS)
            # Take top candidates who pass gates
            top_alts = [
                r for r in ranked if r.get("gate_passed")
            ][:5]
            if not top_alts:
                top_alts = ranked[:3]

            alternative_candidates = top_alts
            _log_message(
                messages, "find_alternatives",
                f"Found {len(alternative_candidates)} alternative candidate(s)",
            )
        except Exception as exc:
            logger.error("Failed to fetch alternative candidates: %s", exc)
            _log_message(
                messages, "find_alternatives",
                f"Error fetching alternatives: {exc}",
            )

        return {
            "alternative_candidates": alternative_candidates,
            "messages": messages,
        }

    return find_alternatives


# ---------------------------------------------------------------------------
# Node 3: Resolve
# ---------------------------------------------------------------------------
async def _resolve(state: ConflictResolutionState) -> dict:
    conflicts = state.get("conflicts") or []
    assignment = state.get("assignment") or {}
    person = state.get("person") or {}
    alternative_candidates = state.get("alternative_candidates") or []
    messages: list = list(state.get("messages") or [])
    resolutions: list[dict] = []

    alloc_pct = float(assignment.get("allocation_pct", 100))
    person_allocated = float(person.get("allocated_pct", 0))

    alt_summaries = [
        {
            "person_id": a.get("person_id"),
            "name": a.get("name"),
            "band": a.get("band"),
            "overall_score": a.get("overall_score"),
            "available_pct": a.get("available_pct",
                                   a.get("factor_scores", {}).get(
                                       "availability_headroom", 0) * 100),
        }
        for a in alternative_candidates[:5]
    ]

    for conflict in conflicts:
        ctype = conflict.get("type", "")
        alternatives: list[dict] = []

        if ctype == "overallocation":
            headroom = max(0.0, 100.0 - person_allocated)
            if headroom > 0:
                alternatives.append({
                    "action": "reduce_allocation",
                    "details": {
                        "suggested_allocation_pct": headroom,
                        "original_allocation_pct": alloc_pct,
                    },
                    "trade_off": (
                        f"Reduce allocation from {alloc_pct:.0f}% to "
                        f"{headroom:.0f}% to fit within capacity"
                    ),
                })
            if alt_summaries:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": alt_summaries},
                    "trade_off": "Use an alternative candidate with available capacity",
                })

        elif ctype == "double_booking":
            ex_details = conflict.get("details") or {}
            ex_end = _to_date_or_none(ex_details.get("existing_end_date"))
            if ex_end:
                from datetime import timedelta
                suggested_start = ex_end + timedelta(days=1)
                alternatives.append({
                    "action": "adjust_dates",
                    "details": {
                        "suggested_start_date": suggested_start.isoformat(),
                        "original_start_date": assignment.get("start_date"),
                    },
                    "trade_off": (
                        f"Delay start to {suggested_start.isoformat()} "
                        f"after existing assignment ends"
                    ),
                })
            if alt_summaries:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": alt_summaries},
                    "trade_off": "Use an alternative candidate without scheduling conflicts",
                })

        elif ctype == "band_mismatch":
            alternatives.append({
                "action": "request_exception",
                "details": {
                    "person_band": person.get("band"),
                    "required_band": (state.get("opportunity") or {}).get("band_required"),
                },
                "trade_off": "Escalate for exception approval by engagement partner",
            })
            higher_band_alts = [
                a for a in alt_summaries
                if _band_rank(a.get("band")) >= _band_rank(
                    (state.get("opportunity") or {}).get("band_required"))
            ]
            if higher_band_alts:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": higher_band_alts},
                    "trade_off": "Use a candidate at the required band or higher",
                })

        elif ctype == "cert_expired":
            cert_details = conflict.get("details") or {}
            alternatives.append({
                "action": "recertification",
                "details": {
                    "certification": cert_details.get("certification"),
                    "expired_on": cert_details.get("expiry_date"),
                },
                "trade_off": "Person can renew certification; assignment delayed until renewal",
            })
            certified_alts = alt_summaries[:3] if alt_summaries else []
            if certified_alts:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": certified_alts},
                    "trade_off": "Use an alternative candidate with valid certification",
                })

        elif ctype == "on_leave":
            next_available = person.get("next_available_date")
            if next_available:
                alternatives.append({
                    "action": "defer_start",
                    "details": {
                        "suggested_start_date": str(next_available),
                    },
                    "trade_off": f"Defer assignment start until after leave ends ({next_available})",
                })
            if alt_summaries:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": alt_summaries},
                    "trade_off": "Use an alternative candidate who is available now",
                })

        else:
            # Unknown conflict type -- generic suggestion
            if alt_summaries:
                alternatives.append({
                    "action": "substitute_candidate",
                    "details": {"candidates": alt_summaries},
                    "trade_off": "Use an alternative candidate",
                })

        resolutions.append({
            "conflict_type": ctype,
            "conflict_description": conflict.get("description", ""),
            "alternatives": alternatives,
        })

    _log_message(
        messages, "resolver",
        f"Proposed resolutions for {len(resolutions)} conflict(s)",
    )

    # -- Optional LLM enrichment --
    if resolutions and settings.ANTHROPIC_API_KEY:
        system = (
            "You are a staffing conflict resolver. For each detected conflict, "
            "propose 1-3 concrete alternatives. Prioritize minimal disruption: "
            "adjust dates/allocation before substituting people. Output JSON: "
            "{resolutions: [{conflict_type, alternatives: [{action, details, "
            "trade_off}]}]}."
        )
        user_payload = _json.dumps({
            "assignment": assignment,
            "person_name": person.get("name"),
            "conflicts": conflicts,
            "deterministic_resolutions": resolutions,
            "alternative_candidates": alt_summaries,
        }, default=str)
        llm_text = await _llm_call(system, user_payload)
        if llm_text:
            parsed = _parse_json_from_text(llm_text)
            if parsed and isinstance(parsed.get("resolutions"), list):
                # Merge LLM alternatives into existing resolutions
                llm_by_type = {
                    r.get("conflict_type"): r.get("alternatives", [])
                    for r in parsed["resolutions"]
                }
                for res in resolutions:
                    llm_alts = llm_by_type.get(res["conflict_type"], [])
                    existing_actions = {
                        a.get("action") for a in res["alternatives"]
                    }
                    for la in llm_alts:
                        if la.get("action") not in existing_actions:
                            res["alternatives"].append(la)
                _log_message(messages, "resolver", "LLM enriched resolutions")

    return {"resolutions": resolutions, "messages": messages}


# ---------------------------------------------------------------------------
# Node 4: Mediate
# ---------------------------------------------------------------------------
async def _mediate(state: ConflictResolutionState) -> dict:
    conflicts = state.get("conflicts") or []
    resolutions = state.get("resolutions") or []
    alternative_candidates = state.get("alternative_candidates") or []
    assignment = state.get("assignment") or {}
    person = state.get("person") or {}
    messages: list = list(state.get("messages") or [])

    # Deterministic mediation logic
    has_hard_block = any(
        c.get("severity") == "hard_block" for c in conflicts
    )
    hard_block_types = {
        c.get("type") for c in conflicts if c.get("severity") == "hard_block"
    }

    if not conflicts:
        recommendation = {
            "action": "proceed",
            "modifications": {},
            "reasoning": "No conflicts detected; assignment can proceed as proposed.",
        }
    elif has_hard_block:
        # Check if any hard-block has a viable non-substitute resolution
        has_viable_modification = False
        modifications: dict[str, Any] = {}

        for res in resolutions:
            if res["conflict_type"] in hard_block_types:
                for alt in res.get("alternatives", []):
                    action = alt.get("action", "")
                    if action not in ("substitute_candidate", "request_exception"):
                        has_viable_modification = True
                        modifications[res["conflict_type"]] = {
                            "action": action,
                            "details": alt.get("details", {}),
                        }
                        break

        if has_viable_modification and "on_leave" not in hard_block_types:
            recommendation = {
                "action": "proceed_with_modifications",
                "modifications": modifications,
                "reasoning": (
                    "Hard-block conflict(s) detected but viable modifications "
                    "found: " + ", ".join(
                        f"{k}: {v['action']}" for k, v in modifications.items()
                    )
                ),
            }
        elif alternative_candidates:
            best_alt = alternative_candidates[0]
            recommendation = {
                "action": "substitute",
                "substitute_candidate": {
                    "person_id": best_alt.get("person_id"),
                    "name": best_alt.get("name"),
                    "band": best_alt.get("band"),
                    "overall_score": best_alt.get("overall_score"),
                },
                "reasoning": (
                    f"Hard-block conflict(s) ({', '.join(hard_block_types)}) "
                    f"with no viable modification. Recommending substitute: "
                    f"{best_alt.get('name')} "
                    f"(score: {best_alt.get('overall_score')})"
                ),
            }
        else:
            recommendation = {
                "action": "escalate",
                "reasoning": (
                    f"Hard-block conflict(s) ({', '.join(hard_block_types)}) "
                    f"detected with no viable alternatives. Requires human review."
                ),
            }
    else:
        # Only soft warnings -- proceed with modifications
        modifications = {}
        for res in resolutions:
            # Pick the first non-substitute alternative
            for alt in res.get("alternatives", []):
                if alt.get("action") != "substitute_candidate":
                    modifications[res["conflict_type"]] = {
                        "action": alt["action"],
                        "details": alt.get("details", {}),
                    }
                    break
            else:
                # All alternatives are substitutes; record as-is
                if res.get("alternatives"):
                    modifications[res["conflict_type"]] = {
                        "action": res["alternatives"][0]["action"],
                        "details": res["alternatives"][0].get("details", {}),
                    }

        recommendation = {
            "action": "proceed_with_modifications",
            "modifications": modifications,
            "reasoning": (
                "Soft-warning conflict(s) detected. Recommended adjustments: "
                + ", ".join(
                    f"{k}: {v['action']}" for k, v in modifications.items()
                )
            ),
        }

    _log_message(
        messages, "mediator",
        f"Recommendation: {recommendation['action']} -- {recommendation['reasoning']}",
    )

    # -- Optional LLM mediation --
    if conflicts and settings.ANTHROPIC_API_KEY:
        system = (
            "You are a staffing mediator. Review all conflicts and proposed "
            "resolutions. Select the best resolution for each conflict. If any "
            "hard-block conflict has no viable resolution, recommend escalation "
            "or substitution. Output JSON: {action: 'proceed'|"
            "'proceed_with_modifications'|'substitute'|'escalate', "
            "modifications: {...}, reasoning: '...'}."
        )
        user_payload = _json.dumps({
            "assignment": assignment,
            "person_name": person.get("name"),
            "conflicts": conflicts,
            "resolutions": resolutions,
            "alternative_candidates": [
                {
                    "person_id": a.get("person_id"),
                    "name": a.get("name"),
                    "band": a.get("band"),
                    "overall_score": a.get("overall_score"),
                }
                for a in alternative_candidates[:5]
            ],
            "deterministic_recommendation": recommendation,
        }, default=str)
        llm_text = await _llm_call(system, user_payload)
        if llm_text:
            parsed = _parse_json_from_text(llm_text)
            if parsed and parsed.get("action") in (
                "proceed", "proceed_with_modifications", "substitute", "escalate",
            ):
                # Use LLM recommendation but keep deterministic as fallback reasoning
                parsed.setdefault("reasoning", recommendation.get("reasoning", ""))
                parsed.setdefault("modifications", recommendation.get("modifications", {}))
                recommendation = parsed
                _log_message(messages, "mediator", "LLM refined recommendation")

    return {"recommendation": recommendation, "messages": messages}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def _build_graph(pool: Any):
    """Compile the StateGraph with all four nodes wired in sequence."""
    find_alternatives = _build_find_alternatives(pool)

    graph = StateGraph(ConflictResolutionState)
    graph.add_node("detect", _detect)
    graph.add_node("find_alternatives", find_alternatives)
    graph.add_node("resolve", _resolve)
    graph.add_node("mediate", _mediate)

    graph.set_entry_point("detect")
    graph.add_edge("detect", "find_alternatives")
    graph.add_edge("find_alternatives", "resolve")
    graph.add_edge("resolve", "mediate")
    graph.add_edge("mediate", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_conflict_resolution(
    pool: Any,
    assignment_details: dict,
    person: dict,
    opportunity: dict,
) -> dict:
    """Run the conflict resolution pipeline.

    Parameters
    ----------
    pool : asyncpg.Pool
        Database connection pool.
    assignment_details : dict
        Proposed assignment: ``opportunity_id``, ``person_id``,
        ``start_date``, ``end_date``, ``allocation_pct``.
    person : dict
        Person profile including ``allocated_pct``, ``active_assignments``,
        ``certifications``, ``status``, ``band``, etc.
    opportunity : dict
        Opportunity/requirement dict with ``band_required``,
        ``mandatory_certs``, ``region``, etc.

    Returns
    -------
    dict
        ``{conflicts, resolutions, recommendation, alternative_candidates,
        messages}``
    """
    compiled = _build_graph(pool)

    initial_state: ConflictResolutionState = {
        "assignment": assignment_details,
        "person": person,
        "opportunity": opportunity,
        "conflicts": [],
        "resolutions": [],
        "recommendation": None,
        "alternative_candidates": [],
        "messages": [],
    }

    final_state = await compiled.ainvoke(initial_state)

    return {
        "conflicts": final_state.get("conflicts", []),
        "resolutions": final_state.get("resolutions", []),
        "recommendation": final_state.get("recommendation"),
        "alternative_candidates": final_state.get("alternative_candidates", []),
        "messages": final_state.get("messages", []),
    }
