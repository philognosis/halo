"""
Multi-agent LangGraph debate for team composition proposals.

Three agents debate the optimal team structure for a project:
  1. Proposer  — proposes an initial team composition
  2. Critic    — reviews the proposal and raises concerns
  3. Negotiator — mediates and produces a final consensus

The debate runs for up to 3 rounds. If the Critic approves or the
Negotiator produces a consensus, the loop terminates early.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.team_shaping import propose_team_shape
from src.config import settings

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TeamCompositionState(TypedDict, total=False):
    project: dict          # project profile from DB
    round: int             # current debate round (0-indexed)
    proposals: list        # list of proposal dicts per round
    critiques: list        # list of critique strings per round
    consensus: dict | None # final agreed team shape
    messages: list         # agent-to-agent message log for audit trail


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _make_message(agent: str, round_num: int, content: str) -> dict:
    """Create a structured agent message for the audit trail."""
    return {"agent": agent, "round": round_num, "content": content}


async def _llm_call(system: str, user: str) -> str:
    """Make an async LLM call via the Anthropic SDK.

    Returns the text content of the response. Raises on failure so callers
    can fall back to deterministic behaviour.
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Extract text from the response content blocks.
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def _extract_json(text: str, expect_key: str = "roles") -> dict | None:
    """Best-effort extraction of a JSON object from LLM output.

    Looks for the outermost ``{…}`` block that contains *expect_key*.
    Returns the parsed dict or ``None`` on failure.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        parsed = json.loads(text[start:end])
        if isinstance(parsed, dict) and expect_key in parsed:
            return parsed
    except (ValueError, json.JSONDecodeError):
        pass
    return None


def _project_summary(project: dict) -> str:
    """One-line project description for LLM prompts."""
    parts = [
        f"Project: {project.get('project_name', 'N/A')}",
        f"Client: {project.get('client', 'N/A')}",
        f"Industry: {project.get('industry', 'N/A')}",
        f"Function: {project.get('function', 'N/A')}",
        f"Region: {project.get('region', 'N/A')}",
    ]
    description = project.get("description")
    if description:
        parts.append(f"Description: {description}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PROPOSER_SYSTEM = (
    "You are a staffing team composition expert. Given a project profile, "
    "propose a team structure with specific roles, headcounts, and rationale "
    "for each role. Consider the industry, function, region, and project scope. "
    "Output JSON: {\"roles\": [{\"role\": \"...\", \"count\": N, "
    "\"rationale\": \"...\"}], \"total_fte\": N}."
)

CRITIC_SYSTEM = (
    "You are a staffing efficiency critic. Review a proposed team structure "
    "for a project and identify concerns: overstaffing, missing roles, skill "
    "gaps, budget inefficiency, or role redundancy. Be specific and actionable. "
    "If the proposal is solid, say APPROVED with brief justification."
)

NEGOTIATOR_SYSTEM = (
    "You are a staffing mediator. Given a team proposal and critique, produce "
    "the final team structure. Accept valid critiques by adjusting roles/counts. "
    "Defend justified choices. Output the final JSON: {\"roles\": "
    "[{\"role\": \"...\", \"count\": N, \"rationale\": \"...\"}], "
    "\"total_fte\": N}."
)


# ---------------------------------------------------------------------------
# Graph node factories (closures over pool)
# ---------------------------------------------------------------------------

def _build_graph(pool: Any):  # noqa: C901 — complexity from 4 nodes is acceptable
    """Build and compile the team-composition debate graph."""

    async def propose(state: TeamCompositionState) -> dict:
        """Proposer agent: generate or refine a team proposal."""
        project = state.get("project") or {}
        round_num = state.get("round", 0)
        proposals = list(state.get("proposals") or [])
        messages = list(state.get("messages") or [])

        # Build the baseline from the deterministic template.
        baseline = await propose_team_shape(pool, project.get("id", ""))
        baseline_roles = []
        if baseline and baseline.get("suggested_team"):
            for opp in baseline["suggested_team"].get("opportunities", []):
                baseline_roles.append({
                    "role": opp.get("role_title", "Unknown"),
                    "count": 1,
                    "rationale": opp.get("rationale", ""),
                })

        proposal: dict | None = None

        if settings.ANTHROPIC_API_KEY:
            try:
                # Build context for the LLM.
                user_parts = [_project_summary(project)]
                user_parts.append(
                    f"\nBaseline template roles:\n{json.dumps(baseline_roles, indent=2)}"
                )
                if round_num > 0:
                    # Include previous critique so the proposer can refine.
                    critiques = state.get("critiques") or []
                    if critiques:
                        user_parts.append(
                            f"\nPrevious critique (round {round_num - 1}):\n"
                            f"{critiques[-1]}"
                        )
                    prev_proposals = state.get("proposals") or []
                    if prev_proposals:
                        user_parts.append(
                            f"\nPrevious proposal:\n"
                            f"{json.dumps(prev_proposals[-1], indent=2)}"
                        )
                    user_parts.append(
                        "\nRefine your proposal addressing the critique above."
                    )

                text = await _llm_call(PROPOSER_SYSTEM, "\n".join(user_parts))
                proposal = _extract_json(text, "roles")
            except Exception as exc:
                logger.warning(
                    "Proposer LLM call failed (round %d): %s", round_num, exc
                )

        # Fallback: use the deterministic baseline.
        if proposal is None:
            total = sum(r.get("count", 1) for r in baseline_roles)
            proposal = {"roles": baseline_roles, "total_fte": total}

        proposals.append(proposal)
        msg = _make_message("proposer", round_num, json.dumps(proposal))
        messages.append(msg)
        logger.info(
            "Proposer (round %d): %d roles, %s FTE",
            round_num,
            len(proposal.get("roles", [])),
            proposal.get("total_fte"),
        )
        return {"proposals": proposals, "messages": messages}

    async def critique(state: TeamCompositionState) -> dict:
        """Critic agent: review the latest proposal."""
        project = state.get("project") or {}
        round_num = state.get("round", 0)
        proposals = state.get("proposals") or []
        critiques = list(state.get("critiques") or [])
        messages = list(state.get("messages") or [])

        latest_proposal = proposals[-1] if proposals else {}
        critique_text = "APPROVED: no concerns."

        if settings.ANTHROPIC_API_KEY:
            try:
                user_msg = (
                    f"{_project_summary(project)}\n\n"
                    f"Proposed team structure:\n"
                    f"{json.dumps(latest_proposal, indent=2)}\n\n"
                    f"Review this proposal. If it looks solid, respond with "
                    f"APPROVED and a brief justification."
                )
                critique_text = await _llm_call(CRITIC_SYSTEM, user_msg)
            except Exception as exc:
                logger.warning(
                    "Critic LLM call failed (round %d): %s", round_num, exc
                )
                critique_text = "APPROVED: unable to critique (LLM unavailable)."

        critiques.append(critique_text)
        msg = _make_message("critic", round_num, critique_text)
        messages.append(msg)
        logger.info("Critic (round %d): %s", round_num, critique_text[:120])
        return {"critiques": critiques, "messages": messages}

    async def negotiate(state: TeamCompositionState) -> dict:
        """Negotiator agent: produce consensus from proposal + critique."""
        project = state.get("project") or {}
        round_num = state.get("round", 0)
        proposals = state.get("proposals") or []
        critiques = state.get("critiques") or []
        messages = list(state.get("messages") or [])

        latest_proposal = proposals[-1] if proposals else {}
        latest_critique = critiques[-1] if critiques else ""

        # If critic approved, accept the proposal directly.
        is_approved = "APPROVED" in latest_critique.upper()

        consensus: dict | None = None

        if is_approved:
            consensus = latest_proposal
            msg_content = (
                "Critic approved the proposal. Accepting as final consensus."
            )
        elif settings.ANTHROPIC_API_KEY:
            try:
                user_msg = (
                    f"{_project_summary(project)}\n\n"
                    f"Current proposal:\n"
                    f"{json.dumps(latest_proposal, indent=2)}\n\n"
                    f"Critique:\n{latest_critique}\n\n"
                    f"Produce the final team structure resolving the critique."
                )
                text = await _llm_call(NEGOTIATOR_SYSTEM, user_msg)
                consensus = _extract_json(text, "roles")
                if consensus is None:
                    # Could not parse — let the loop continue with the proposal.
                    msg_content = (
                        f"Could not parse negotiator output. "
                        f"Continuing debate. Raw: {text[:300]}"
                    )
                    logger.warning(
                        "Negotiator output unparseable (round %d)", round_num
                    )
                else:
                    msg_content = json.dumps(consensus)
            except Exception as exc:
                logger.warning(
                    "Negotiator LLM call failed (round %d): %s", round_num, exc
                )
                msg_content = f"Negotiator LLM failed: {exc}"
        else:
            # No API key — deterministic fallback: accept proposal as-is.
            consensus = latest_proposal
            msg_content = (
                "No LLM available. Accepting latest proposal as consensus."
            )

        msg = _make_message("negotiator", round_num, msg_content)
        messages.append(msg)

        result: dict = {"messages": messages}
        if consensus is not None:
            result["consensus"] = consensus
            logger.info(
                "Negotiator (round %d): consensus reached, %d roles",
                round_num,
                len(consensus.get("roles", [])),
            )
        else:
            logger.info("Negotiator (round %d): no consensus yet", round_num)
        return result

    def check_consensus(state: TeamCompositionState) -> str:
        """Conditional edge: END if consensus reached or max rounds hit."""
        if state.get("consensus") is not None:
            return END
        round_num = state.get("round", 0)
        if round_num >= MAX_ROUNDS - 1:
            return END
        return "increment_round"

    async def increment_round(state: TeamCompositionState) -> dict:
        """Bump the round counter before looping back to propose."""
        return {"round": state.get("round", 0) + 1}

    # -- Build the graph --
    graph = StateGraph(TeamCompositionState)
    graph.add_node("propose", propose)
    graph.add_node("critique", critique)
    graph.add_node("negotiate", negotiate)
    graph.add_node("increment_round", increment_round)

    graph.set_entry_point("propose")
    graph.add_edge("propose", "critique")
    graph.add_edge("critique", "negotiate")
    graph.add_conditional_edges(
        "negotiate",
        check_consensus,
        {"increment_round": "increment_round", END: END},
    )
    graph.add_edge("increment_round", "propose")

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_team_composition_debate(
    pool: Any, project_id: str
) -> dict[str, Any]:
    """Run the multi-agent team composition debate and return the result.

    Parameters
    ----------
    pool : asyncpg.Pool
        Database connection pool.
    project_id : str
        UUID of the project to propose a team for.

    Returns
    -------
    dict
        ``{"project_id", "project_name", "roles", "total_fte",
        "debate_rounds", "messages"}`` — compatible with the shape from
        ``propose_team_shape`` but enriched with debate metadata.
    """
    import asyncpg

    # Fetch the project profile.
    async with pool.acquire() as conn:
        project = await conn.fetchrow(
            """
            SELECT id::TEXT, project_name, client, industry, sector, function,
                   region, start_date::TEXT, end_date::TEXT, status
            FROM project WHERE id = $1::UUID
            """,
            project_id,
        )

    if project is None:
        logger.error("Project not found: %s", project_id)
        return {
            "project_id": project_id,
            "project_name": None,
            "roles": [],
            "total_fte": 0,
            "debate_rounds": 0,
            "messages": [],
        }

    project_dict = dict(project)

    # Build and run the debate graph.
    graph = _build_graph(pool)
    initial_state: TeamCompositionState = {
        "project": project_dict,
        "round": 0,
        "proposals": [],
        "critiques": [],
        "consensus": None,
        "messages": [],
    }

    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("Team composition debate failed: %s", exc)
        # Fall back to the deterministic proposal.
        fallback = await propose_team_shape(pool, project_id)
        roles = []
        if fallback.get("suggested_team"):
            for opp in fallback["suggested_team"].get("opportunities", []):
                roles.append({
                    "role": opp.get("role_title", "Unknown"),
                    "count": 1,
                    "rationale": opp.get("rationale", ""),
                })
        return {
            "project_id": project_id,
            "project_name": project_dict.get("project_name"),
            "roles": roles,
            "total_fte": len(roles),
            "debate_rounds": 0,
            "messages": [
                _make_message(
                    "system", 0,
                    f"Debate failed, fell back to deterministic proposal: {exc}",
                )
            ],
        }

    # Extract the final result.
    consensus = final_state.get("consensus")
    proposals = final_state.get("proposals") or []
    debate_rounds = final_state.get("round", 0) + 1
    all_messages = final_state.get("messages") or []

    # If no consensus was reached after max rounds, use the last proposal.
    if consensus is None and proposals:
        consensus = proposals[-1]
        all_messages.append(
            _make_message(
                "system", debate_rounds - 1,
                "Max rounds reached without consensus. Using last proposal.",
            )
        )

    roles = consensus.get("roles", []) if consensus else []
    total_fte = consensus.get("total_fte", 0) if consensus else 0
    # Recompute total_fte if it looks off.
    computed_fte = sum(r.get("count", 1) for r in roles)
    if total_fte == 0 and computed_fte > 0:
        total_fte = computed_fte

    return {
        "project_id": project_id,
        "project_name": project_dict.get("project_name"),
        "roles": roles,
        "total_fte": total_fte,
        "debate_rounds": debate_rounds,
        "messages": all_messages,
    }
