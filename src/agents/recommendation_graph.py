"""
LangGraph recommendation pipeline.

Nodes:
  1. load_requirement  — fetch the requirement dict if not supplied
  2. gather_pool       — fetch + enrich the candidate pool
  3. resolve_skills    — SKOS-transitive skill matching (with direct fallback)
  4. score             — deterministic rank_candidates
  5. explain           — optional LLM (or deterministic template) rationale

The LLM is used ONLY in ``explain`` and ONLY to phrase a rationale grounded in
the already-computed factor scores. It never computes scores or invents data.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.data_access import (
    enrich_candidates,
    fetch_candidate_pool,
    fetch_requirement,
    fetch_skos_skill_matches,
)
from src.agents.scoring import rank_candidates
from src.config import settings

logger = logging.getLogger(__name__)


class RecommendationState(TypedDict, total=False):
    opportunity_id: Optional[str]
    requirement: Optional[dict]
    candidates: list
    ranked: list
    top_n: int
    explain: bool
    explanations: dict


# ---------------------------------------------------------------------------
# Nodes (closures over pool + sparql_client)
# ---------------------------------------------------------------------------
def _build_graph(pool: Any, sparql_client: Any):
    async def load_requirement(state: RecommendationState) -> dict:
        requirement = state.get("requirement")
        if not requirement:
            opp_id = state.get("opportunity_id")
            requirement = await fetch_requirement(pool, opp_id) if opp_id else {}
        return {"requirement": requirement}

    async def gather_pool(state: RecommendationState) -> dict:
        requirement = state.get("requirement") or {}
        region = requirement.get("region")
        band_required = requirement.get("band_required") or "Analyst"
        candidates = await fetch_candidate_pool(pool, region, band_required)
        await enrich_candidates(pool, candidates)
        return {"candidates": candidates}

    async def resolve_skills(state: RecommendationState) -> dict:
        requirement = state.get("requirement") or {}
        candidates = state.get("candidates") or []

        required_skill_ids = [
            s["skill_id"]
            for s in (requirement.get("mandatory_skills") or [])
            + (requirement.get("nice_skills") or [])
            if s.get("skill_id")
        ]

        sparql_matches: dict[str, set] = {}
        if required_skill_ids and sparql_client is not None:
            person_uris = [
                f"{settings.STF_NAMESPACE}person/{c['person_id']}" for c in candidates
            ]
            sparql_matches = await fetch_skos_skill_matches(
                sparql_client,
                settings.STF_NAMESPACE,
                person_uris,
                required_skill_ids,
            )

        required_set = set(required_skill_ids)
        for c in candidates:
            # Direct Postgres skill_id intersection (always available).
            direct = {
                s.get("skill_id")
                for s in (c.get("skills") or [])
                if s.get("skill_id") in required_set
            }
            sparql_set = sparql_matches.get(c["person_id"], set())
            # Prefer SPARQL; merge with direct so we never lose a direct match.
            c["matched_skill_ids"] = direct | sparql_set
        return {"candidates": candidates}

    async def score(state: RecommendationState) -> dict:
        requirement = state.get("requirement") or {}
        candidates = state.get("candidates") or []
        ranked = rank_candidates(candidates, requirement)
        return {"ranked": ranked}

    async def explain(state: RecommendationState) -> dict:
        ranked = state.get("ranked") or []
        top_n = state.get("top_n", settings.RECOMMENDATION_TOP_N)
        requirement = state.get("requirement") or {}
        top = ranked[:top_n]

        if settings.ANTHROPIC_API_KEY:
            try:
                explanations = await _llm_explain(top, requirement)
            except Exception as exc:  # pragma: no cover - LLM failure
                logger.warning("LLM explanation failed, using template: %s", exc)
                explanations = {r["person_id"]: _template_rationale(r) for r in top}
        else:
            explanations = {r["person_id"]: _template_rationale(r) for r in top}

        return {"explanations": explanations}

    def needs_explain(state: RecommendationState) -> str:
        return "explain" if state.get("explain") else END

    graph = StateGraph(RecommendationState)
    graph.add_node("load_requirement", load_requirement)
    graph.add_node("gather_pool", gather_pool)
    graph.add_node("resolve_skills", resolve_skills)
    graph.add_node("score", score)
    graph.add_node("explain", explain)

    graph.set_entry_point("load_requirement")
    graph.add_edge("load_requirement", "gather_pool")
    graph.add_edge("gather_pool", "resolve_skills")
    graph.add_edge("resolve_skills", "score")
    graph.add_conditional_edges("score", needs_explain, {"explain": "explain", END: END})
    graph.add_edge("explain", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Rationale generation
# ---------------------------------------------------------------------------
def _template_rationale(scored: dict) -> str:
    factors = scored.get("factor_scores", {})
    top_factors = sorted(factors.items(), key=lambda kv: kv[1], reverse=True)[:3]
    strengths = ", ".join(f"{k.replace('_', ' ')} ({v:.0%})" for k, v in top_factors)
    matched = scored.get("matched_skills") or []
    skill_note = (
        f" Matched skills: {', '.join(matched[:5])}." if matched else ""
    )
    gate = "" if scored.get("gate_passed") else " NOTE: fails mandatory gate(s): " + "; ".join(
        scored.get("gate_failures", [])
    )
    return (
        f"{scored.get('name')} scores {scored.get('overall_score')} overall; "
        f"strongest on {strengths}.{skill_note}{gate}"
    )


async def _llm_explain(top: list[dict], requirement: dict) -> dict[str, str]:
    """Use the LLM to phrase a 1-2 sentence rationale per candidate.

    The model receives ONLY the precomputed factor scores / matched data and is
    instructed not to introduce new facts.
    """
    import json as _json

    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=1024,
        timeout=30,
    )

    payload = {
        "role_title": requirement.get("role_title"),
        "band_required": requirement.get("band_required"),
        "candidates": [
            {
                "person_id": r["person_id"],
                "name": r["name"],
                "overall_score": r["overall_score"],
                "gate_passed": r["gate_passed"],
                "gate_failures": r["gate_failures"],
                "factor_scores": r["factor_scores"],
                "matched_skills": r["matched_skills"],
                "missing_mandatory": r["missing_mandatory"],
            }
            for r in top
        ],
    }

    system = (
        "You are a staffing analyst. For each candidate, write a 1-2 sentence "
        "rationale grounded ONLY in the provided factor scores and matched data. "
        "Do NOT invent skills, projects, or facts not present. Do NOT recompute "
        "scores. Return a JSON object mapping person_id to the rationale string."
    )
    user = (
        "Candidate scoring data (do not add facts beyond this):\n"
        + _json.dumps(payload, default=str)
        + "\n\nReturn only a JSON object: {person_id: rationale}."
    )

    resp = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        parsed = _json.loads(text[start:end])
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except (ValueError, _json.JSONDecodeError):
        pass
    # Fall back to template if parsing fails.
    return {r["person_id"]: _template_rationale(r) for r in top}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_recommendation(
    pool: Any,
    sparql_client: Any,
    opportunity_id: str | None = None,
    requirement: dict | None = None,
    top_n: int = 5,
    explain: bool = True,
) -> dict[str, Any]:
    """Run the recommendation pipeline and return requirement + ranked + top."""
    graph = _build_graph(pool, sparql_client)
    initial: RecommendationState = {
        "opportunity_id": opportunity_id,
        "requirement": requirement,
        "top_n": top_n,
        "explain": explain,
    }
    final = await graph.ainvoke(initial)

    ranked = final.get("ranked") or []
    explanations = final.get("explanations") or {}
    for r in ranked:
        if r["person_id"] in explanations:
            r["rationale"] = explanations[r["person_id"]]

    top = ranked[:top_n]
    return {
        "requirement": final.get("requirement") or {},
        "ranked": ranked,
        "top": top,
    }
