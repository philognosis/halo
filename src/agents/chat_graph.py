"""
LangGraph conversational agent (the natural-language entry point).

The LLM (langchain-anthropic ChatAnthropic) is used ONLY for:
  - intent classification
  - entity extraction
  - final response synthesis (grounded in result data)

It NEVER computes scores or invents candidates — all scoring goes through the
deterministic tools. When ANTHROPIC_API_KEY is None the agent degrades
gracefully using regex/keyword fallbacks (``_fallback_classify`` /
``_fallback_extract``) and a deterministic synthesis.

Nodes: classify_intent -> extract_entities -> resolve -> route(by intent) ->
synthesize.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.tools import (
    compare_profiles,
    propose_team,
    recommend_for_opportunity,
    recommend_for_spec,
    shortlist_candidate,
)
from src.bridge.sparql_client import build_skos_resolve
from src.config import settings

logger = logging.getLogger(__name__)

_INTENTS = {"SEARCH", "COMPARE", "SHORTLIST", "TEAM_SHAPE", "STATUS", "GREETING", "UNKNOWN"}

_BANDS = [
    "Analyst",
    "Consultant",
    "Senior Consultant",
    "Manager",
    "Senior Manager",
    "Director",
    "Partner",
]
_REGIONS = {"EMEA", "Americas", "APAC"}


class ChatState(TypedDict, total=False):
    message: str
    context: dict
    intent: str
    entities: dict
    requirement: dict
    result: dict
    response: str
    history: list


# ---------------------------------------------------------------------------
# Fallback (no-LLM) intent + entity logic
# ---------------------------------------------------------------------------
def _fallback_classify(message: str) -> str:
    m = message.lower().strip()
    if not m:
        return "UNKNOWN"
    if re.search(r"\b(hi|hello|hey|good morning|good afternoon|thanks|thank you)\b", m):
        if len(m.split()) <= 4:
            return "GREETING"
    if re.search(r"\b(compare|versus|vs\.?|side by side|difference between)\b", m):
        return "COMPARE"
    if re.search(r"\b(shortlist|short-list|short list|assign|put forward|propose .* for)\b", m):
        return "SHORTLIST"
    if re.search(r"\b(team shape|shape .* team|team structure|staff .* project|propose .* team|build .* team)\b", m):
        return "TEAM_SHAPE"
    if re.search(r"\b(status|progress|where is|what.?s happening|state of)\b", m):
        return "STATUS"
    if re.search(r"\b(find|search|recommend|who|looking for|need|candidates?|someone)\b", m):
        return "SEARCH"
    return "UNKNOWN"


def _fallback_extract(message: str) -> dict:
    m = message
    lower = m.lower()
    entities: dict[str, Any] = {
        "role": None,
        "role_category": None,
        "skills": [],
        "region": None,
        "location": None,
        "band": None,
        "industry": None,
        "function": None,
        "certs": [],
        "language": None,
        "citizenship": None,
        "dates": {"start": None, "end": None},
        "person_names": [],
        "opportunity_ref": None,
        "project_ref": None,
        "allocation_pct": None,
    }

    # Region
    for r in _REGIONS:
        if r.lower() in lower:
            entities["region"] = r

    # Band (match longest first)
    for b in sorted(_BANDS, key=len, reverse=True):
        if b.lower() in lower:
            entities["band"] = b
            break

    # Role category keywords
    role_cats = [
        "engineer", "manager", "associate", "business_analyst", "expert",
        "designer", "consultant", "architect", "lead", "analyst", "specialist",
    ]
    for rc in role_cats:
        if rc.replace("_", " ") in lower:
            entities["role_category"] = rc
            break

    # Skills — naive keyword list of common skills/tech.
    known_skills = [
        "spark", "python", "java", "scala", "sql", "aws", "azure", "gcp",
        "kubernetes", "docker", "kafka", "tableau", "powerbi", "togaf",
        "machine learning", "ml", "data", "etl", "react", "agile", "scrum",
    ]
    for s in known_skills:
        if re.search(rf"\b{re.escape(s)}\b", lower):
            entities["skills"].append(s)

    # Location: "in <Word>" (e.g. London)
    loc = re.search(r"\bin ([A-Z][a-zA-Z]+)", m)
    if loc:
        candidate_loc = loc.group(1)
        if candidate_loc not in _REGIONS:
            entities["location"] = candidate_loc

    # UUID references for opportunity/project
    uuid_re = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    opp = re.search(rf"opportunit\w*\s+({uuid_re})", m)
    if opp:
        entities["opportunity_ref"] = opp.group(1)
    proj = re.search(rf"project\s+({uuid_re})", m)
    if proj:
        entities["project_ref"] = proj.group(1)

    # allocation percentage
    pct = re.search(r"(\d{1,3})\s?%", m)
    if pct:
        entities["allocation_pct"] = int(pct.group(1))

    # Role title heuristic: words before "in"/"with"
    role = re.search(r"\b(?:a|an|the)?\s*((?:senior |junior |lead )?[a-z ]*?(?:engineer|consultant|analyst|architect|manager|designer|specialist))\b", lower)
    if role:
        entities["role"] = role.group(1).strip()

    return entities


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------
def _get_llm():
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=1024,
        timeout=30,
    )


async def _llm_classify(message: str) -> str:
    llm = _get_llm()
    system = (
        "Classify the user's staffing request into exactly one intent label. "
        "Valid labels: SEARCH (find/recommend candidates), COMPARE (compare "
        "named people), SHORTLIST (put a person forward for an opportunity), "
        "TEAM_SHAPE (propose a team structure for a project), STATUS (ask about "
        "an assignment/opportunity status), GREETING, UNKNOWN. "
        "Respond with ONLY the label."
    )
    resp = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": message}]
    )
    text = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip().upper()
    for label in _INTENTS:
        if label in text:
            return label
    return "UNKNOWN"


async def _llm_extract(message: str) -> dict:
    llm = _get_llm()
    schema_hint = {
        "role": "string|null",
        "role_category": "one of engineer/manager/associate/business_analyst/expert/designer/consultant/architect/lead/analyst/specialist|null",
        "skills": ["string"],
        "region": "EMEA|Americas|APAC|null",
        "location": "string|null",
        "band": "Analyst|Consultant|Senior Consultant|Manager|Senior Manager|Director|Partner|null",
        "industry": "string|null",
        "function": "string|null",
        "certs": ["string"],
        "language": "string|null",
        "citizenship": "string|null",
        "dates": {"start": "YYYY-MM-DD|null", "end": "YYYY-MM-DD|null"},
        "person_names": ["string"],
        "opportunity_ref": "string|null",
        "project_ref": "string|null",
        "allocation_pct": "integer|null",
    }
    system = (
        "Extract structured staffing entities from the user's message. Return "
        "ONLY a JSON object matching this shape (use null/empty when absent):\n"
        + json.dumps(schema_hint)
    )
    resp = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": message}]
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        if isinstance(data, dict):
            # Merge with the fallback to guarantee all keys exist.
            base = _fallback_extract("")
            base.update({k: v for k, v in data.items() if k in base})
            if "dates" not in data or not isinstance(data.get("dates"), dict):
                base["dates"] = {"start": None, "end": None}
            return base
    except (ValueError, json.JSONDecodeError):
        pass
    return _fallback_extract(message)


# ---------------------------------------------------------------------------
# SKOS resolution of skill/role labels -> notations
# ---------------------------------------------------------------------------
async def _resolve_skill_labels(sparql_client: Any, labels: list[str]) -> list[dict]:
    """Map labels to {skill_id, name}. Falls back to label as skill_id."""
    resolved: list[dict] = []
    for label in labels:
        skill_id = label
        if sparql_client is not None:
            try:
                rows = await sparql_client.select(build_skos_resolve(label))
                if rows:
                    concept = rows[0].get("concept", "")
                    notation = concept.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                    if notation:
                        skill_id = notation
            except Exception as exc:  # pragma: no cover - SPARQL failure
                logger.debug("SKOS resolve failed for %r: %s", label, exc)
        resolved.append({"skill_id": skill_id, "name": label})
    return resolved


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def _build_graph(pool: Any, sparql_client: Any):
    has_llm = bool(settings.ANTHROPIC_API_KEY)
    if not has_llm:
        logger.warning(
            "ANTHROPIC_API_KEY not set — chat agent running in degraded "
            "(regex/keyword) mode; no NL synthesis."
        )

    async def classify_intent(state: ChatState) -> dict:
        message = state.get("message", "")
        if has_llm:
            try:
                intent = await _llm_classify(message)
            except Exception as exc:  # pragma: no cover
                logger.warning("LLM classify failed, using fallback: %s", exc)
                intent = _fallback_classify(message)
        else:
            intent = _fallback_classify(message)
        return {"intent": intent}

    async def extract_entities(state: ChatState) -> dict:
        message = state.get("message", "")
        if has_llm:
            try:
                entities = await _llm_extract(message)
            except Exception as exc:  # pragma: no cover
                logger.warning("LLM extract failed, using fallback: %s", exc)
                entities = _fallback_extract(message)
        else:
            entities = _fallback_extract(message)
        return {"entities": entities}

    async def resolve(state: ChatState) -> dict:
        entities = state.get("entities") or {}
        context = state.get("context") or {}

        skill_labels = entities.get("skills") or []
        resolved_skills = await _resolve_skill_labels(sparql_client, skill_labels)

        nice_langs = []
        if entities.get("language"):
            nice_langs.append({"code": entities["language"], "min_prof": "professional"})
        nice_cits = []
        if entities.get("citizenship"):
            nice_cits.append(entities["citizenship"])

        requirement = {
            "role_title": entities.get("role"),
            "role_category": entities.get("role_category"),
            "band_required": entities.get("band"),
            "region": entities.get("region") or context.get("region"),
            "office": entities.get("location"),
            "industry": entities.get("industry"),
            "function": entities.get("function"),
            "mandatory_skills": [],
            "nice_skills": resolved_skills,
            "mandatory_certs": [],
            "nice_certs": entities.get("certs") or [],
            "mandatory_quals": [],
            "mandatory_languages": [],
            "nice_languages": nice_langs,
            "mandatory_citizenships": [],
            "nice_citizenships": nice_cits,
            "requested_allocation_pct": entities.get("allocation_pct") or 100,
        }
        return {"requirement": requirement}

    async def route(state: ChatState) -> dict:
        intent = state.get("intent", "UNKNOWN")
        entities = state.get("entities") or {}
        context = state.get("context") or {}
        requirement = state.get("requirement") or {}

        result: dict[str, Any] = {}

        opp_ref = entities.get("opportunity_ref") or context.get("opportunity_id")
        project_ref = entities.get("project_ref") or context.get("project_id")

        try:
            if intent == "SEARCH":
                if opp_ref:
                    result = await recommend_for_opportunity(
                        pool, sparql_client, opp_ref, top_n=settings.RECOMMENDATION_TOP_N
                    )
                else:
                    result = await recommend_for_spec(
                        pool, sparql_client, requirement, top_n=settings.RECOMMENDATION_TOP_N
                    )

            elif intent == "COMPARE":
                names = entities.get("person_names") or []
                person_ids = await _resolve_person_names(pool, names, context)
                if person_ids:
                    result = await compare_profiles(pool, sparql_client, person_ids, opp_ref)
                else:
                    result = {"error": "Could not resolve the people to compare. "
                              "Provide person names or ids."}

            elif intent == "SHORTLIST":
                person_ids = await _resolve_person_names(
                    pool, entities.get("person_names") or [], context
                )
                person_id = (person_ids[0] if person_ids else context.get("person_id"))
                dates = entities.get("dates") or {}
                start = dates.get("start")
                end = dates.get("end")
                if opp_ref and person_id and start:
                    result = await shortlist_candidate(
                        pool,
                        opp_ref,
                        person_id,
                        start,
                        end,
                        allocation_pct=entities.get("allocation_pct") or 100,
                    )
                else:
                    missing = []
                    if not opp_ref:
                        missing.append("opportunity")
                    if not person_id:
                        missing.append("person")
                    if not start:
                        missing.append("start date")
                    result = {
                        "error": "Missing required info to shortlist: "
                        + ", ".join(missing)
                        + "."
                    }

            elif intent == "TEAM_SHAPE":
                if project_ref:
                    result = await propose_team(pool, project_ref)
                else:
                    result = {"error": "Please provide a project reference to shape a team."}

            elif intent == "STATUS":
                result = await _query_status(pool, opp_ref, context)

            else:  # GREETING / UNKNOWN
                result = {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("route action failed (intent=%s): %s", intent, exc)
            result = {"error": f"Action failed: {exc}"}

        return {"result": result}

    async def synthesize(state: ChatState) -> dict:
        intent = state.get("intent", "UNKNOWN")
        result = state.get("result") or {}
        message = state.get("message", "")

        if has_llm and intent not in ("GREETING", "UNKNOWN"):
            try:
                response = await _llm_synthesize(message, intent, result)
                return {"response": response}
            except Exception as exc:  # pragma: no cover
                logger.warning("LLM synthesize failed, using template: %s", exc)

        return {"response": _template_synthesize(intent, result)}

    graph = StateGraph(ChatState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("resolve", resolve)
    graph.add_node("route", route)
    graph.add_node("synthesize", synthesize)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "extract_entities")
    graph.add_edge("extract_entities", "resolve")
    graph.add_edge("resolve", "route")
    graph.add_edge("route", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Helpers used by route
# ---------------------------------------------------------------------------
async def _resolve_person_names(pool: Any, names: list[str], context: dict) -> list[str]:
    """Resolve person names (or ids) to person ids."""
    import asyncpg  # noqa: PLC0415

    ids: list[str] = []
    uuid_re = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    plain_names = []
    for n in names:
        if uuid_re.match(n):
            ids.append(n)
        else:
            plain_names.append(n)

    if plain_names:
        async with pool.acquire() as conn:
            for n in plain_names:
                try:
                    rows = await conn.fetch(
                        "SELECT id::TEXT FROM person WHERE name ILIKE $1 LIMIT 1",
                        f"%{n}%",
                    )
                    if rows:
                        ids.append(rows[0]["id"])
                except asyncpg.PostgresError:
                    continue

    if not ids and context.get("person_id"):
        ids.append(context["person_id"])
    return ids


async def _query_status(pool: Any, opportunity_id: str | None, context: dict) -> dict:
    """Query DB for assignment/opportunity status."""
    opp_id = opportunity_id or context.get("opportunity_id")
    if not opp_id:
        return {"error": "Provide an opportunity reference to check status."}
    async with pool.acquire() as conn:
        opp = await conn.fetchrow(
            "SELECT id::TEXT, role_title, status FROM opportunity WHERE id = $1::UUID",
            opp_id,
        )
        if opp is None:
            return {"error": "Opportunity not found."}
        assignments = await conn.fetch(
            """
            SELECT a.id::TEXT, a.status, a.allocation_pct,
                   a.start_date::TEXT, a.end_date::TEXT,
                   p.name AS person_name
            FROM assignment a
            JOIN person p ON p.id = a.person_id
            WHERE a.opportunity_id = $1::UUID
            ORDER BY a.assigned_at DESC
            """,
            opp_id,
        )
    return {
        "opportunity": dict(opp),
        "assignments": [dict(a) for a in assignments],
    }


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------
def _template_synthesize(intent: str, result: dict) -> str:
    if intent == "GREETING":
        return (
            "Hello! I can help you find candidates, compare profiles, shortlist "
            "someone for an opportunity, propose a team shape, or check status. "
            "What would you like to do?"
        )
    if intent == "UNKNOWN":
        return (
            "I'm not sure what you'd like. Try: 'find a senior data engineer in "
            "London with Spark', 'compare Alice and Bob', or 'shape a team for "
            "project <id>'."
        )
    if result.get("error"):
        return result["error"]

    if intent == "SEARCH":
        top = result.get("top") or []
        if not top:
            return "No matching candidates were found for that requirement."
        lines = ["Top candidates:"]
        for r in top:
            note = "" if r.get("gate_passed") else " (does not meet all mandatory requirements)"
            lines.append(
                f"  - {r['name']} ({r['band']}, {r['region']}) — score "
                f"{r['overall_score']}{note}"
                + (f": {r.get('rationale')}" if r.get("rationale") else "")
            )
        return "\n".join(lines)

    if intent == "COMPARE":
        profiles = result.get("profiles") or []
        if not profiles:
            return "No profiles to compare."
        lines = ["Comparison:"]
        for p in profiles:
            score = p.get("overall_score")
            score_txt = f" — score {score}" if score is not None else ""
            lines.append(f"  - {p['name']} ({p.get('band')}){score_txt}")
        return "\n".join(lines)

    if intent == "SHORTLIST":
        return (
            f"Shortlisted. Assignment {result.get('assignment_id')} created "
            f"(status short_listed); the approval workflow will start "
            f"automatically ({result.get('workflow_id')})."
        )

    if intent == "TEAM_SHAPE":
        team = result.get("suggested_team") or {}
        opps = team.get("opportunities") or []
        lines = [f"Suggested team for {result.get('project_name')}:"]
        for o in opps:
            lines.append(
                f"  - {o['role_title']} ({o['band_required']}, {o['role_category']}) — "
                f"{o['rationale']}"
            )
        return "\n".join(lines)

    if intent == "STATUS":
        opp = result.get("opportunity") or {}
        assignments = result.get("assignments") or []
        lines = [
            f"Opportunity '{opp.get('role_title')}' is {opp.get('status')}.",
        ]
        if assignments:
            lines.append("Assignments:")
            for a in assignments:
                lines.append(
                    f"  - {a['person_name']}: {a['status']} "
                    f"({a['allocation_pct']}%)"
                )
        else:
            lines.append("No assignments yet.")
        return "\n".join(lines)

    return "Done."


async def _llm_synthesize(message: str, intent: str, result: dict) -> str:
    llm = _get_llm()
    system = (
        "You are a staffing assistant. Write a concise, helpful natural-language "
        "reply grounded ONLY in the provided result data. Cite candidate names, "
        "scores, and factor highlights when present. Do NOT invent any facts, "
        "candidates, or scores beyond what is in the data. If the data contains "
        "an 'error' field, relay it helpfully."
    )
    user = (
        f"User asked: {message}\nIntent: {intent}\nResult data (ground truth):\n"
        + json.dumps(result, default=str)
    )
    resp = await llm.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    return resp.content if isinstance(resp.content, str) else str(resp.content)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_chat(
    pool: Any,
    sparql_client: Any,
    message: str,
    context: dict | None = None,
) -> dict[str, Any]:
    """Run the chat agent and return {intent, response, result, entities}."""
    graph = _build_graph(pool, sparql_client)
    initial: ChatState = {
        "message": message,
        "context": context or {},
        "history": [],
    }
    final = await graph.ainvoke(initial)
    return {
        "intent": final.get("intent", "UNKNOWN"),
        "response": final.get("response", ""),
        "result": final.get("result", {}),
        "entities": final.get("entities", {}),
    }
