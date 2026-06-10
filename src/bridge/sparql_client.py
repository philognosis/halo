"""
Reusable async SPARQL client — the canonical Python bridge to Jena Fuseki.

This module is shared by the FastAPI service (candidate search, health checks)
and the ABox sync loop. It is intentionally free of any Temporal imports so it
can be imported into the API process without dragging in the workflow sandbox.

The client uses a single long-lived ``httpx.AsyncClient`` (created in
``__init__``) and must be closed via ``aclose()`` on shutdown.

Module-level pure functions build parameterised SPARQL strings. Parameterisation
is done via SPARQL ``VALUES`` clauses and IRI/literal escaping rather than naive
string interpolation, to avoid SPARQL injection.
"""
from __future__ import annotations

import textwrap
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

# Band ordering for >= comparisons (mirrors sparql_activities.BAND_ORDER).
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
# Escaping helpers
# ---------------------------------------------------------------------------
def _escape_literal(value: str) -> str:
    """Escape a string for safe inclusion inside a SPARQL double-quoted literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _escape_iri(value: str) -> str:
    """Escape an IRI for inclusion inside angle brackets."""
    # Disallow characters that would terminate the IRI / inject syntax.
    return value.replace("\\", "%5C").replace(">", "%3E").replace("<", "%3C").replace(
        '"', "%22"
    ).replace(" ", "%20")


def bands_gte(required_band: str) -> list[str]:
    """Return all bands that are >= required_band in seniority order."""
    try:
        idx = BAND_ORDER.index(required_band)
    except ValueError:
        idx = 0
    return BAND_ORDER[idx:]


def _is_numeric_datatype(datatype: str | None) -> bool:
    if not datatype:
        return False
    numeric = {
        XSD + t
        for t in (
            "integer",
            "decimal",
            "float",
            "double",
            "int",
            "long",
            "short",
            "byte",
            "nonNegativeInteger",
            "positiveInteger",
            "unsignedInt",
            "unsignedLong",
        )
    }
    return datatype in numeric


def _coerce_binding(cell: dict[str, Any]) -> Any:
    """Convert a single SPARQL JSON result binding cell into a Python value."""
    value = cell.get("value")
    datatype = cell.get("datatype")
    if value is None:
        return None
    if _is_numeric_datatype(datatype):
        try:
            if datatype and datatype.endswith(("integer", "int", "long", "short", "byte")):
                return int(value)
            return float(value)
        except (TypeError, ValueError):
            return value
    if datatype == XSD + "boolean":
        return value in ("true", "1")
    return value


# ---------------------------------------------------------------------------
# SparqlClient
# ---------------------------------------------------------------------------
class SparqlClient:
    """Async SPARQL query/update/ask client backed by a shared httpx client."""

    def __init__(
        self,
        sparql_endpoint: str,
        update_endpoint: str,
        timeout: float = 20.0,
    ) -> None:
        self.sparql_endpoint = sparql_endpoint
        self.update_endpoint = update_endpoint
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def select(self, query: str) -> list[dict[str, Any]]:
        """Run a SELECT query and return a list of flat (value-only) dicts."""
        resp = await self._client.post(
            self.sparql_endpoint,
            data={"query": query},
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        bindings = data.get("results", {}).get("bindings", [])
        rows: list[dict[str, Any]] = []
        for binding in bindings:
            rows.append({var: _coerce_binding(cell) for var, cell in binding.items()})
        return rows

    async def update(self, update: str) -> bool:
        """Run a SPARQL UPDATE (form-encoded ``update=``). True on 2xx."""
        resp = await self._client.post(
            self.update_endpoint,
            data={"update": update},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return 200 <= resp.status_code < 300

    async def ask(self, query: str) -> bool:
        """Run an ASK query and return the boolean result."""
        resp = await self._client.post(
            self.sparql_endpoint,
            data={"query": query},
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get("boolean", False))

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Query builders (pure functions returning SPARQL strings)
# ---------------------------------------------------------------------------
def build_candidate_search(
    stf_ns: str,
    required_skills: list[str],
    required_band: str,
    region: str | None,
) -> str:
    """
    Build a candidate-search SELECT.

    Matches stf:Employee instances with:
      - band concept in the set of bands >= required_band (via VALUES)
      - at least one skill matching each required concept through
        ``skos:broaderTransitive*`` (a skill more specific than the requirement
        satisfies it)
      - availability_phase != stf:FullyAllocated

    Returns columns: person_uri, name, band, region, matched_skills (count),
    availability_phase. Ordered by matched_skills DESC.
    """
    eligible_bands = bands_gte(required_band)
    band_uris = " ".join(
        f"<{_escape_iri(stf_ns + b.replace(' ', '_'))}>" for b in eligible_bands
    )

    skill_blocks: list[str] = []
    for i, skill in enumerate(required_skills):
        # A required skill may be supplied as a concept-id/notation or a label.
        # We match employees whose own skill concept is the required concept or
        # any narrower concept (skos:broaderTransitive* from owned → required).
        req_uri = _escape_iri(stf_ns + skill.replace(" ", "_"))
        skill_blocks.append(
            textwrap.dedent(
                f"""
                OPTIONAL {{
                  ?person stf:hasSkill ?ownedSkill{i} .
                  ?ownedSkill{i} skos:broaderTransitive* <{req_uri}> .
                  BIND(1 AS ?skillMatch{i})
                }}"""
            )
        )

    score_expr = (
        " + ".join(f"COALESCE(?skillMatch{i}, 0)" for i in range(len(required_skills)))
        or "0"
    )

    if region:
        region_filter = f'FILTER(STR(?region) = "{_escape_literal(region)}")'
    else:
        region_filter = ""

    return textwrap.dedent(
        f"""
        PREFIX stf:  <{stf_ns}>
        PREFIX skos: <{SKOS}>
        PREFIX xsd:  <{XSD}>
        PREFIX rdfs: <{RDFS}>

        SELECT ?person ?name ?band ?region ?availabilityPhase
               ({score_expr} AS ?matched_skills)
        WHERE {{
          VALUES ?bandConcept {{ {band_uris} }}
          ?person a stf:Employee ;
                  stf:hasBand ?bandConcept ;
                  stf:hasName ?name ;
                  stf:hasRegion ?region ;
                  stf:hasAvailabilityPhase ?availabilityPhase .
          FILTER(?availabilityPhase != stf:FullyAllocated)
          {region_filter}
          {"".join(skill_blocks)}
        }}
        ORDER BY DESC(?matched_skills) ?band
        LIMIT 25
        """
    ).strip()


def build_availability_check(
    stf_ns: str,
    person_uri: str,
    start_date: str,
    end_date: str,
) -> str:
    """Build a SELECT that returns overlapping active allocations for a person."""
    p_uri = _escape_iri(person_uri)
    s = _escape_literal(start_date)
    e = _escape_literal(end_date)
    return textwrap.dedent(
        f"""
        PREFIX stf: <{stf_ns}>
        PREFIX xsd: <{XSD}>

        SELECT ?allocation ?allocStart ?allocEnd ?allocPct
        WHERE {{
          <{p_uri}> stf:hasActiveAllocation ?allocation .
          ?allocation stf:allocationStartDate ?allocStart ;
                      stf:allocationEndDate   ?allocEnd ;
                      stf:allocationPercent   ?allocPct .
          FILTER(
            ?allocStart <= "{e}"^^xsd:date &&
            ?allocEnd   >= "{s}"^^xsd:date
          )
        }}
        """
    ).strip()


def build_skos_resolve(label: str) -> str:
    """Build a SELECT resolving a prefLabel/altLabel (case-insensitive) to concepts."""
    lit = _escape_literal(label)
    return textwrap.dedent(
        f"""
        PREFIX skos: <{SKOS}>

        SELECT DISTINCT ?concept ?prefLabel
        WHERE {{
          ?concept skos:altLabel|skos:prefLabel ?l .
          FILTER(LCASE(STR(?l)) = LCASE("{lit}"))
          OPTIONAL {{ ?concept skos:prefLabel ?prefLabel . }}
        }}
        LIMIT 10
        """
    ).strip()
