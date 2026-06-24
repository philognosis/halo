"""
Multi-agent LangGraph for candidate arbitration.

Three specialist agents evaluate candidates from different angles, then an
arbiter produces the final ranking.  When no LLM API key is configured the
agents fall back to deterministic heuristics so the pipeline never hard-fails.

Graph topology::

    START → score_deterministic → assess_availability ─┐
                                 assess_skills ────────┤
                                                       └→ arbitrate → END

``assess_availability`` and ``assess_skills`` are independent nodes that both
depend on ``score_deterministic``.  ``arbitrate`` depends on both.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.scoring import DEFAULT_WEIGHTS, rank_candidates
from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
_AVAILABILITY_SYSTEM = (
    "You are a staffing availability specialist. Evaluate candidates for a role "
    "based on: current allocation percentage, availability phase, location/region "
    "match, time zone alignment, upcoming project end dates. Rank candidates by "
    "availability fit and explain each ranking. Output JSON: "
    '{rankings: [{person_id, rank, reasoning}]}.'
)

_SKILLS_SYSTEM = (
    "You are a staffing skills specialist. Evaluate candidates for a role based "
    "on: skill match depth, certification relevance, qualification level, "
    "industry experience, role category fit. Rank candidates by skills fit and "
    "explain each ranking. Output JSON: "
    '{rankings: [{person_id, rank, reasoning}]}.'
)

_ARBITER_SYSTEM = (
    "You are a staffing arbitration judge. You have two specialist assessments "
    "(availability and skills) plus deterministic scores. Produce the final "
    "ranking by weighing both perspectives. When specialists disagree, explain "
    "your tiebreak reasoning. Output JSON: "
    '{final_ranking: [{person_id, rank, score, reasoning}]}.'
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class ArbitrationState(TypedDict, total=False):
    requirement: dict
    candidates: list
    deterministic_scores: list
    availability_assessment: dict
    skills_assessment: dict
    final_ranking: list
    messages: list


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
async def _llm_call(system: str, user_content: str) -> dict | None:
    """Call Claude via the Anthropic SDK.  Returns parsed JSON or ``None``."""
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        return None

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        text = response.content[0].text
        # Strip markdown fences if present.
        text = text.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            last_fence = text.rfind("```")
            text = text[first_nl + 1 : last_fence].strip()
        return json.loads(text)
    except ImportError:
        logger.warning("anthropic SDK not installed — falling back to heuristic")
        return None
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON response: %s", exc)
        return None
    except Exception:
        logger.exception("LLM call failed")
        return None


# ---------------------------------------------------------------------------
# Candidate summary helpers (build compact context for LLM prompts)
# ---------------------------------------------------------------------------
def _candidate_summary_for_availability(
    candidate: dict, scored: dict | None,
) -> dict[str, Any]:
    """Compact view of a candidate for the availability agent."""
    return {
        "person_id": candidate.get("person_id"),
        "name": candidate.get("name"),
        "region": candidate.get("region"),
        "office": candidate.get("office"),
        "available_pct": candidate.get("available_pct"),
        "allocated_pct": candidate.get("allocated_pct"),
        "availability_phase": candidate.get("availability_phase"),
        "status": candidate.get("status"),
        "factor_scores": {
            k: scored["factor_scores"][k]
            for k in ("availability_headroom", "location")
            if scored and k in scored.get("factor_scores", {})
        },
    }


def _candidate_summary_for_skills(
    candidate: dict, scored: dict | None,
) -> dict[str, Any]:
    """Compact view of a candidate for the skills agent."""
    return {
        "person_id": candidate.get("person_id"),
        "name": candidate.get("name"),
        "role_category": candidate.get("role_category"),
        "band": candidate.get("band"),
        "skills": [
            {
                "skill_name": s.get("skill_name"),
                "proficiency_level": s.get("proficiency_level"),
            }
            for s in candidate.get("skills", [])
        ],
        "certifications": [
            c.get("name") for c in candidate.get("certifications", []) if c.get("is_valid")
        ],
        "qualifications": candidate.get("qualifications", []),
        "industry_exposure": candidate.get("industry_exposure", []),
        "factor_scores": {
            k: scored["factor_scores"][k]
            for k in (
                "skills",
                "certifications",
                "qualifications",
                "industry_fit",
                "role_category_fit",
                "function_fit",
            )
            if scored and k in scored.get("factor_scores", {})
        },
    }


def _scores_by_person(deterministic_scores: list) -> dict[str, dict]:
    return {s["person_id"]: s for s in deterministic_scores}


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
async def score_deterministic(state: ArbitrationState) -> dict:
    """Run the deterministic scorer from ``scoring.py``."""
    candidates = state["candidates"]
    requirement = state["requirement"]

    scored = rank_candidates(candidates, requirement, DEFAULT_WEIGHTS)

    return {
        "deterministic_scores": scored,
        "messages": state.get("messages", [])
            + [{"agent": "deterministic", "note": f"Scored {len(scored)} candidates"}],
    }


async def assess_availability(state: ArbitrationState) -> dict:
    """Availability specialist assessment."""
    candidates = state["candidates"]
    requirement = state["requirement"]
    det_scores = state.get("deterministic_scores", [])
    by_pid = _scores_by_person(det_scores)

    summaries = [
        _candidate_summary_for_availability(c, by_pid.get(c.get("person_id")))
        for c in candidates
    ]

    user_prompt = (
        f"Requirement: {json.dumps(_compact_requirement(requirement))}\n\n"
        f"Candidates:\n{json.dumps(summaries, indent=2)}"
    )

    result = await _llm_call(_AVAILABILITY_SYSTEM, user_prompt)

    if result and "rankings" in result:
        assessment = {
            "source": "llm",
            "rankings": result["rankings"],
        }
    else:
        # Fallback: rank by availability_headroom factor score descending.
        fallback = sorted(det_scores, key=lambda s: s.get("factor_scores", {}).get("availability_headroom", 0), reverse=True)
        assessment = {
            "source": "fallback",
            "rankings": [
                {
                    "person_id": s["person_id"],
                    "rank": i + 1,
                    "reasoning": f"availability_headroom={s.get('factor_scores', {}).get('availability_headroom', 0):.3f}",
                }
                for i, s in enumerate(fallback)
            ],
        }

    return {
        "availability_assessment": assessment,
        "messages": state.get("messages", [])
            + [{"agent": "availability", "source": assessment["source"],
                "note": f"Ranked {len(assessment['rankings'])} candidates"}],
    }


async def assess_skills(state: ArbitrationState) -> dict:
    """Skills specialist assessment."""
    candidates = state["candidates"]
    requirement = state["requirement"]
    det_scores = state.get("deterministic_scores", [])
    by_pid = _scores_by_person(det_scores)

    summaries = [
        _candidate_summary_for_skills(c, by_pid.get(c.get("person_id")))
        for c in candidates
    ]

    user_prompt = (
        f"Requirement: {json.dumps(_compact_requirement(requirement))}\n\n"
        f"Candidates:\n{json.dumps(summaries, indent=2)}"
    )

    result = await _llm_call(_SKILLS_SYSTEM, user_prompt)

    if result and "rankings" in result:
        assessment = {
            "source": "llm",
            "rankings": result["rankings"],
        }
    else:
        # Fallback: rank by skills factor score descending.
        fallback = sorted(det_scores, key=lambda s: s.get("factor_scores", {}).get("skills", 0), reverse=True)
        assessment = {
            "source": "fallback",
            "rankings": [
                {
                    "person_id": s["person_id"],
                    "rank": i + 1,
                    "reasoning": f"skills={s.get('factor_scores', {}).get('skills', 0):.3f}",
                }
                for i, s in enumerate(fallback)
            ],
        }

    return {
        "skills_assessment": assessment,
        "messages": state.get("messages", [])
            + [{"agent": "skills", "source": assessment["source"],
                "note": f"Ranked {len(assessment['rankings'])} candidates"}],
    }


async def arbitrate(state: ArbitrationState) -> dict:
    """Arbiter: fuse specialist assessments + deterministic scores."""
    det_scores = state.get("deterministic_scores", [])
    avail = state.get("availability_assessment", {})
    skills = state.get("skills_assessment", {})

    by_pid = _scores_by_person(det_scores)

    user_prompt = (
        f"Deterministic scores:\n{json.dumps(det_scores, indent=2)}\n\n"
        f"Availability assessment:\n{json.dumps(avail, indent=2)}\n\n"
        f"Skills assessment:\n{json.dumps(skills, indent=2)}"
    )

    result = await _llm_call(_ARBITER_SYSTEM, user_prompt)

    if result and "final_ranking" in result:
        ranking = result["final_ranking"]
    else:
        # Fallback: use the deterministic ranking directly.
        ranking = [
            {
                "person_id": s["person_id"],
                "rank": i + 1,
                "score": s["overall_score"],
                "reasoning": "deterministic ranking (arbiter fallback)",
            }
            for i, s in enumerate(det_scores)
        ]

    # Build lookup maps for specialist ranks.
    avail_rank_map: dict[str, int] = {}
    for r in avail.get("rankings", []):
        avail_rank_map[r["person_id"]] = r["rank"]

    skills_rank_map: dict[str, int] = {}
    for r in skills.get("rankings", []):
        skills_rank_map[r["person_id"]] = r["rank"]

    # Merge all data into final output rows.
    final: list[dict[str, Any]] = []
    for entry in ranking:
        pid = entry["person_id"]
        det = by_pid.get(pid, {})
        final.append({
            "person_id": pid,
            "name": det.get("name"),
            "score": entry.get("score", det.get("overall_score")),
            "gate_passed": det.get("gate_passed"),
            "factor_scores": det.get("factor_scores"),
            "availability_rank": avail_rank_map.get(pid),
            "skills_rank": skills_rank_map.get(pid),
            "final_rank": entry["rank"],
            "reasoning": entry.get("reasoning", ""),
        })

    return {
        "final_ranking": final,
        "messages": state.get("messages", [])
            + [{"agent": "arbiter", "note": f"Final ranking has {len(final)} candidates"}],
    }


# ---------------------------------------------------------------------------
# Helper: compact requirement for LLM context
# ---------------------------------------------------------------------------
def _compact_requirement(requirement: dict) -> dict:
    """Strip the requirement dict to the fields most relevant for LLM context."""
    return {
        "role_title": requirement.get("role_title"),
        "role_category": requirement.get("role_category"),
        "band_required": requirement.get("band_required"),
        "industry": requirement.get("industry"),
        "function": requirement.get("function"),
        "region": requirement.get("region"),
        "mandatory_skills": [
            s.get("name") for s in requirement.get("mandatory_skills", [])
        ],
        "nice_skills": [
            s.get("name") for s in requirement.get("nice_skills", [])
        ],
        "mandatory_certs": requirement.get("mandatory_certs", []),
    }


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_arbitration_graph() -> StateGraph:
    """Build and compile the arbitration LangGraph."""
    graph = StateGraph(ArbitrationState)

    graph.add_node("score_deterministic", score_deterministic)
    graph.add_node("assess_availability", assess_availability)
    graph.add_node("assess_skills", assess_skills)
    graph.add_node("arbitrate", arbitrate)

    graph.set_entry_point("score_deterministic")

    # Both specialist assessments run after deterministic scoring.
    graph.add_edge("score_deterministic", "assess_availability")
    graph.add_edge("score_deterministic", "assess_skills")

    # Arbiter runs after both specialists.
    graph.add_edge("assess_availability", "arbitrate")
    graph.add_edge("assess_skills", "arbitrate")

    graph.add_edge("arbitrate", END)

    return graph.compile()


# Compiled graph singleton (lazy).
_compiled_graph: Any = None


def _get_graph() -> Any:
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        _compiled_graph = build_arbitration_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_candidate_arbitration(
    pool: Any,
    sparql_client: Any,
    opportunity_id: str,
    candidates: list,
    requirement: dict,
    top_n: int = 5,
) -> dict:
    """Run the full arbitration pipeline and return the top-N ranked candidates.

    Parameters
    ----------
    pool:
        asyncpg connection pool (unused here but kept for pipeline signature
        compatibility — data is already fetched).
    sparql_client:
        SPARQL client (unused here — SKOS matching already done during
        enrichment).
    opportunity_id:
        The opportunity being staffed (for logging/tracing).
    candidates:
        Already-enriched candidate dicts (from ``data_access``).
    requirement:
        The requirement dict (from ``data_access.fetch_requirement``).
    top_n:
        Number of top candidates to return.

    Returns
    -------
    dict with keys:
        ``top`` — list of ranked candidate dicts with scores and reasoning.
        ``arbitration_log`` — agent message log for transparency.
    """
    logger.info(
        "Starting candidate arbitration for opportunity %s with %d candidates",
        opportunity_id,
        len(candidates),
    )

    initial_state: ArbitrationState = {
        "requirement": requirement,
        "candidates": candidates,
        "deterministic_scores": [],
        "availability_assessment": {},
        "skills_assessment": {},
        "final_ranking": [],
        "messages": [],
    }

    graph = _get_graph()

    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception:
        logger.exception(
            "Arbitration graph failed for opportunity %s — falling back to deterministic ranking",
            opportunity_id,
        )
        scored = rank_candidates(candidates, requirement, DEFAULT_WEIGHTS)
        return {
            "top": [
                {
                    "person_id": s["person_id"],
                    "name": s.get("name"),
                    "score": s["overall_score"],
                    "gate_passed": s["gate_passed"],
                    "factor_scores": s["factor_scores"],
                    "availability_rank": None,
                    "skills_rank": None,
                    "final_rank": i + 1,
                    "reasoning": "deterministic fallback (graph error)",
                }
                for i, s in enumerate(scored[:top_n])
            ],
            "arbitration_log": [{"agent": "error", "note": "Graph execution failed"}],
        }

    ranking = final_state.get("final_ranking", [])
    messages = final_state.get("messages", [])

    top = ranking[:top_n]

    logger.info(
        "Arbitration complete for opportunity %s — returning top %d of %d",
        opportunity_id,
        len(top),
        len(ranking),
    )

    return {
        "top": top,
        "arbitration_log": messages,
    }
