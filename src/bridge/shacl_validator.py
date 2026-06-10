"""
PySHACL wrapper for ad-hoc graph validation.

``pyshacl.validate`` is synchronous and CPU-bound, so it is run in a thread
executor to avoid blocking the event loop. Used by the API preflight endpoint
and any caller that wants to validate a Turtle data graph against the shapes
graph + ontology.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# RDF / SHACL vocabulary
SH = "http://www.w3.org/ns/shacl#"


def _validate_sync(
    data_ttl: str,
    shapes_ttl_path: str,
    ontology_ttl_path: str,
) -> dict[str, Any]:
    """Synchronous SHACL validation; returns conforms/violations/warnings dict."""
    import pyshacl  # type: ignore
    from rdflib import Graph, URIRef  # type: ignore

    data_graph = Graph()
    data_graph.parse(data=data_ttl, format="turtle")

    shapes_graph = Graph()
    try:
        shapes_graph.parse(shapes_ttl_path, format="turtle")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not load shapes graph %s: %s", shapes_ttl_path, exc)

    ont_graph = Graph()
    try:
        ont_graph.parse(ontology_ttl_path, format="turtle")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not load ontology graph %s: %s", ontology_ttl_path, exc)

    conforms, results_graph, _results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph if len(shapes_graph) else None,
        ont_graph=ont_graph if len(ont_graph) else None,
        inference="rdfs",
        abort_on_first=False,
        allow_warnings=True,
        meta_shacl=False,
    )

    violations: list[str] = []
    warnings: list[str] = []

    sh_result = URIRef(SH + "ValidationResult")
    sh_severity = URIRef(SH + "resultSeverity")
    sh_message = URIRef(SH + "resultMessage")
    sh_focus = URIRef(SH + "focusNode")
    sh_path = URIRef(SH + "resultPath")
    sh_violation = URIRef(SH + "Violation")
    sh_warning = URIRef(SH + "Warning")
    rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

    for result_node in results_graph.subjects(rdf_type, sh_result):
        severity = results_graph.value(result_node, sh_severity)
        message = results_graph.value(result_node, sh_message)
        focus = results_graph.value(result_node, sh_focus)
        path = results_graph.value(result_node, sh_path)
        parts: list[str] = []
        if message:
            parts.append(str(message))
        if focus:
            parts.append(f"focus={focus}")
        if path:
            parts.append(f"path={path}")
        text = " | ".join(parts) if parts else str(result_node)

        if severity == sh_warning:
            warnings.append(text)
        else:
            # Treat Violation (and anything not explicitly a Warning) as a violation.
            violations.append(text)

    return {
        "conforms": bool(conforms),
        "violations": violations,
        "warnings": warnings,
    }


async def validate_graph(
    data_ttl: str,
    shapes_ttl_path: str,
    ontology_ttl_path: str,
) -> dict[str, Any]:
    """
    Validate a Turtle data graph against the SHACL shapes + ontology.

    Runs the synchronous pyshacl validation in a thread executor.

    Returns: {conforms: bool, violations: list[str], warnings: list[str]}.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, _validate_sync, data_ttl, shapes_ttl_path, ontology_ttl_path
        )
    except Exception as exc:
        logger.error("validate_graph failed: %s", exc)
        return {
            "conforms": False,
            "violations": [f"Validation could not run: {exc}"],
            "warnings": [],
        }
