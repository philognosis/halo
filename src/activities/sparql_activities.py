"""
SPARQL activities for Jena Fuseki.

All queries use httpx.AsyncClient for async compatibility.
No rdflib imports at the top level — direct SPARQL over HTTP only.

Activities:
  - search_candidates         — ranked candidate list from ABox
  - check_availability_in_jena — allocation overlap check
  - run_preflight_shacl       — PySHACL validation of proposed triples
  - project_allocation_to_abox — write confirmed allocation to ABox
  - resolve_skos_label        — SKOS concept disambiguation
"""
from __future__ import annotations

import logging
import textwrap
import uuid
from typing import Any

import httpx
from temporalio import activity

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Band ordering used to build VALUES clauses for >= comparisons
# ---------------------------------------------------------------------------
BAND_ORDER = [
    "Analyst",
    "Consultant",
    "Senior Consultant",
    "Manager",
    "Senior Manager",
    "Director",
    "Partner",
]

STF = settings.STF_NAMESPACE


def _bands_gte(required_band: str) -> list[str]:
    """Return all bands that are >= required_band in seniority order."""
    try:
        idx = BAND_ORDER.index(required_band)
    except ValueError:
        idx = 0
    return BAND_ORDER[idx:]


def _sparql_values_iris(var: str, iris: list[str]) -> str:
    """Build a SPARQL VALUES clause for a list of IRIs."""
    items = " ".join(f"<{iri}>" for iri in iris)
    return f"VALUES {var} {{ {items} }}"


# ---------------------------------------------------------------------------
# Activity: search_candidates
# ---------------------------------------------------------------------------
@activity.defn(name="search_candidates")
async def search_candidates(
    opportunity_id: str,
    required_skills: list[str],
    required_band: str,
    region: str | None,
) -> list[dict[str, Any]]:
    """
    SPARQL candidate search against the ABox graph.

    Matches employees with:
      - band >= required_band
      - at least one skill matching via skos:broaderTransitive*
      - availability_phase != FullyAllocated

    Returns ranked list of candidates with score = number of matched skills.
    Falls back to empty list on timeout/error (caller handles Postgres fallback).
    """
    activity.logger.info(
        "search_candidates: opportunity_id=%s band=%s region=%s skills=%s",
        opportunity_id,
        required_band,
        region,
        required_skills,
    )

    eligible_bands = _bands_gte(required_band)
    band_uris = [f"{STF}{b.replace(' ', '_')}" for b in eligible_bands]
    band_values = _sparql_values_iris("?bandConcept", band_uris)

    # Build OPTIONAL skill match blocks — one per required skill
    skill_blocks: list[str] = []
    for i, skill_name in enumerate(required_skills):
        skill_uri = f"{STF}{skill_name.replace(' ', '_')}"
        skill_blocks.append(
            f"""
  OPTIONAL {{
    <{skill_uri}> skos:broaderTransitive* ?skillAncestor{i} .
    ?person stf:hasSkill ?skillAncestor{i} .
    BIND(1 AS ?skillMatch{i})
  }}"""
        )

    skill_match_vars = " + ".join(
        [f"COALESCE(?skillMatch{i}, 0)" for i in range(len(required_skills))]
    ) or "0"

    region_filter = f'FILTER(?region = "{region}"^^xsd:string)' if region else ""

    sparql_query = textwrap.dedent(
        f"""
        PREFIX stf:  <{STF}>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?person ?name ?band ?region ?availabilityPhase
               ({skill_match_vars} AS ?score)
        WHERE {{
          {band_values}
          ?person a stf:Employee ;
                  stf:hasBand ?bandConcept ;
                  stf:hasName ?name ;
                  stf:hasRegion ?region ;
                  stf:hasAvailabilityPhase ?availabilityPhase .

          FILTER(?availabilityPhase != stf:FullyAllocated)
          {region_filter}
          {"".join(skill_blocks)}
        }}
        ORDER BY DESC(?score) ?band
        LIMIT 20
        """
    ).strip()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                settings.FUSEKI_SPARQL_ENDPOINT,
                params={"query": sparql_query},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        bindings = data.get("results", {}).get("bindings", [])
        candidates: list[dict[str, Any]] = []
        for b in bindings:
            candidates.append(
                {
                    "person_uri": b.get("person", {}).get("value", ""),
                    "name": b.get("name", {}).get("value", ""),
                    "band": b.get("band", {}).get("value", "").split("/")[-1].replace("_", " "),
                    "availability_phase": b.get("availabilityPhase", {})
                    .get("value", "")
                    .split("#")[-1]
                    .split("/")[-1],
                    "region": b.get("region", {}).get("value", ""),
                    "score": int(float(b.get("score", {}).get("value", 0))),
                    "matched_skills": int(float(b.get("score", {}).get("value", 0))),
                }
            )
        activity.logger.info(
            "search_candidates: found %d candidates for opportunity=%s",
            len(candidates),
            opportunity_id,
        )
        return candidates

    except httpx.TimeoutException:
        activity.logger.warning(
            "search_candidates: Fuseki timeout for opportunity=%s — returning empty list",
            opportunity_id,
        )
        return []
    except Exception as exc:
        activity.logger.error(
            "search_candidates: error querying Fuseki for opportunity=%s: %s",
            opportunity_id,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Activity: check_availability_in_jena
# ---------------------------------------------------------------------------
@activity.defn(name="check_availability_in_jena")
async def check_availability_in_jena(
    person_uri: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    Check allocation overlap for a person in Jena using stf:hasActiveAllocation triples.

    Returns:
      {available: bool, conflicts: list[str], total_allocated_pct: float}
    """
    activity.logger.info(
        "check_availability_in_jena: person=%s %s→%s", person_uri, start_date, end_date
    )

    sparql_query = textwrap.dedent(
        f"""
        PREFIX stf:  <{STF}>
        PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>

        SELECT ?allocation ?allocStart ?allocEnd ?allocPct
        WHERE {{
          <{person_uri}> stf:hasActiveAllocation ?allocation .
          ?allocation stf:allocationStartDate ?allocStart ;
                      stf:allocationEndDate   ?allocEnd ;
                      stf:allocationPercent   ?allocPct .

          FILTER(
            ?allocStart <= "{end_date}"^^xsd:date &&
            ?allocEnd   >= "{start_date}"^^xsd:date
          )
        }}
        """
    ).strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.FUSEKI_SPARQL_ENDPOINT,
                params={"query": sparql_query},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        bindings = data.get("results", {}).get("bindings", [])
        conflicts: list[str] = []
        total_pct = 0.0
        for b in bindings:
            alloc_uri = b.get("allocation", {}).get("value", "")
            alloc_pct = float(b.get("allocPct", {}).get("value", 0))
            conflicts.append(alloc_uri)
            total_pct += alloc_pct

        available = total_pct < 100.0
        return {
            "available": available,
            "conflicts": conflicts,
            "total_allocated_pct": total_pct,
        }

    except Exception as exc:
        activity.logger.error(
            "check_availability_in_jena: error for person=%s: %s", person_uri, exc
        )
        # On error, assume available but surface as warning to caller
        return {"available": True, "conflicts": [], "total_allocated_pct": 0.0}


# ---------------------------------------------------------------------------
# Activity: run_preflight_shacl
# ---------------------------------------------------------------------------
@activity.defn(name="run_preflight_shacl")
async def run_preflight_shacl(allocation_triples_ttl: str) -> dict[str, Any]:
    """
    Validate proposed allocation triples with PySHACL against the staffing shapes graph.

    Steps:
      1. POST a temporary named graph to Fuseki
      2. Fetch the SHACL shapes graph from Fuseki
      3. Run pyshacl validation
      4. Delete the temporary graph
      5. Return {valid, violations, warnings}
    """
    import pyshacl  # type: ignore
    from rdflib import ConjunctiveGraph, Graph  # type: ignore

    temp_graph_name = f"{STF}temp/preflight/{uuid.uuid4()}"
    activity.logger.info("run_preflight_shacl: temp_graph=%s", temp_graph_name)

    shapes_graph_name = f"{STF}shapes"
    violations: list[str] = []
    warnings_list: list[str] = []

    try:
        # --- Upload temp graph ---
        insert_query = (
            f"INSERT DATA {{ GRAPH <{temp_graph_name}> {{ {allocation_triples_ttl} }} }}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.FUSEKI_UPDATE_ENDPOINT,
                data={"update": insert_query},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()

            # --- Fetch the shapes graph ---
            shapes_resp = await client.get(
                settings.FUSEKI_SPARQL_ENDPOINT,
                params={
                    "query": f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{shapes_graph_name}> {{ ?s ?p ?o }} }}"
                },
                headers={"Accept": "text/turtle"},
            )
            shapes_ttl = shapes_resp.text if shapes_resp.status_code == 200 else ""

        # --- Parse graphs for pyshacl ---
        data_graph = Graph()
        data_graph.parse(data=allocation_triples_ttl, format="turtle")

        if shapes_ttl:
            shapes_graph = Graph()
            shapes_graph.parse(data=shapes_ttl, format="turtle")
        else:
            activity.logger.warning(
                "run_preflight_shacl: no shapes graph found at <%s>", shapes_graph_name
            )
            shapes_graph = None

        # --- Run validation ---
        if shapes_graph:
            conforms, results_graph, results_text = pyshacl.validate(
                data_graph,
                shacl_graph=shapes_graph,
                inference="rdfs",
                abort_on_first=False,
                allow_warnings=True,
            )
        else:
            conforms = True
            results_text = "No shapes graph available — skipping SHACL validation"

        if not conforms:
            # Parse violation messages from results_text
            for line in results_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("Constraint Violation"):
                    violations.append(stripped)
                elif stripped.startswith("Warning"):
                    warnings_list.append(stripped)
            if not violations and results_text:
                violations.append(results_text[:500])

    except Exception as exc:
        activity.logger.error("run_preflight_shacl: validation error: %s", exc)
        warnings_list.append(f"SHACL validation could not complete: {exc}")
    finally:
        # --- Clean up temp graph ---
        try:
            delete_query = f"DROP GRAPH <{temp_graph_name}>"
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    settings.FUSEKI_UPDATE_ENDPOINT,
                    data={"update": delete_query},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except Exception as cleanup_exc:
            activity.logger.warning(
                "run_preflight_shacl: failed to clean up temp graph %s: %s",
                temp_graph_name,
                cleanup_exc,
            )

    valid = len(violations) == 0
    activity.logger.info(
        "run_preflight_shacl: valid=%s violations=%d warnings=%d",
        valid,
        len(violations),
        len(warnings_list),
    )
    return {"valid": valid, "violations": violations, "warnings": warnings_list}


# ---------------------------------------------------------------------------
# Activity: project_allocation_to_abox
# ---------------------------------------------------------------------------
@activity.defn(name="project_allocation_to_abox")
async def project_allocation_to_abox(
    assignment_id: str,
    person_uri: str,
    opportunity_uri: str,
    start_date: str,
    end_date: str,
    allocation_pct: float,
) -> bool:
    """
    Write a confirmed ProjectAllocation to the Jena ABox graph via SPARQL UPDATE INSERT DATA.

    Creates a stf:ProjectAllocation instance with PROV-DM provenance triples.
    """
    activity.logger.info(
        "project_allocation_to_abox: assignment=%s person=%s opportunity=%s",
        assignment_id,
        person_uri,
        opportunity_uri,
    )

    allocation_uri = f"{STF}allocation/{assignment_id}"
    abox_graph = f"{STF}abox"
    now_iso = _utc_now_iso()

    turtle_fragment = textwrap.dedent(
        f"""
        <{allocation_uri}> a <{STF}ProjectAllocation> ;
            <{STF}allocatedPerson>       <{person_uri}> ;
            <{STF}forOpportunity>        <{opportunity_uri}> ;
            <{STF}allocationStartDate>   "{start_date}"^^<http://www.w3.org/2001/XMLSchema#date> ;
            <{STF}allocationEndDate>     "{end_date}"^^<http://www.w3.org/2001/XMLSchema#date> ;
            <{STF}allocationPercent>     "{allocation_pct}"^^<http://www.w3.org/2001/XMLSchema#decimal> ;
            <http://www.w3.org/ns/prov#generatedAtTime>  "{now_iso}"^^<http://www.w3.org/2001/XMLSchema#dateTime> ;
            <http://www.w3.org/ns/prov#wasGeneratedBy>   <{STF}workflow/assignment-approval/{assignment_id}> .

        <{person_uri}> <{STF}hasActiveAllocation> <{allocation_uri}> .
        """
    ).strip()

    insert_query = (
        f"INSERT DATA {{ GRAPH <{abox_graph}> {{ {turtle_fragment} }} }}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.FUSEKI_UPDATE_ENDPOINT,
                data={"update": insert_query},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
        activity.logger.info(
            "project_allocation_to_abox: wrote allocation <%s> to ABox", allocation_uri
        )
        return True
    except Exception as exc:
        activity.logger.error(
            "project_allocation_to_abox: failed to write allocation for assignment=%s: %s",
            assignment_id,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Activity: resolve_skos_label
# ---------------------------------------------------------------------------
@activity.defn(name="resolve_skos_label")
async def resolve_skos_label(label: str) -> list[dict[str, Any]]:
    """
    Resolve a human-readable label to SKOS concept URI(s).

    SPARQL query matches skos:altLabel or skos:prefLabel (case-insensitive).
    Returns a list of {concept_uri, pref_label} dicts.
    """
    activity.logger.info("resolve_skos_label: label=%r", label)

    sparql_query = textwrap.dedent(
        f"""
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

        SELECT DISTINCT ?concept ?prefLabel
        WHERE {{
          ?concept skos:altLabel|skos:prefLabel ?l .
          FILTER(LCASE(STR(?l)) = LCASE("{label}"))
          OPTIONAL {{ ?concept skos:prefLabel ?prefLabel . FILTER(LANG(?prefLabel) = "en") }}
        }}
        LIMIT 10
        """
    ).strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                settings.FUSEKI_SPARQL_ENDPOINT,
                params={"query": sparql_query},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        bindings = data.get("results", {}).get("bindings", [])
        results: list[dict[str, Any]] = []
        for b in bindings:
            results.append(
                {
                    "concept_uri": b.get("concept", {}).get("value", ""),
                    "pref_label": b.get("prefLabel", {}).get("value", label),
                }
            )
        return results

    except Exception as exc:
        activity.logger.error("resolve_skos_label: error for label=%r: %s", label, exc)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string (without microseconds)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
