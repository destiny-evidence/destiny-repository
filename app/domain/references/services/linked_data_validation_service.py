"""Service for validating LinkedDataEnhancements against an OWL/SKOS ontology."""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, Field
from pyld import jsonld
from pyld.jsonld import JsonLdError
from pyshacl import validate as shacl_validate
from pyshacl.errors import ReportableRuntimeError
from rdflib import Graph, URIRef

_STATIC_DIR = Path(__file__).parent.parent / "static"
_ONTOLOGY_PATH = _STATIC_DIR / "evrepo-core.ttl"
_SHAPES_PATH = _STATIC_DIR / "evrepo-core-shapes.ttl"


@functools.cache
def _get_bundled_graphs() -> tuple[Graph, Graph]:
    """Return the bundled ontology and shapes graphs, parsing on first call."""
    ontology = Graph()
    ontology.parse(str(_ONTOLOGY_PATH), format="turtle")
    shapes = Graph()
    shapes.parse(str(_SHAPES_PATH), format="turtle")
    return ontology, shapes


class LinkedDataValidationResult(BaseModel):
    """Result of validating a LinkedDataEnhancement."""

    conforms: bool
    errors: list[str] = Field(default_factory=list)


class LinkedDataValidationService:
    """Validates LinkedDataEnhancements using JSON-LD expansion and SHACL."""

    def __init__(
        self,
        ontology: Graph,
        shapes: Graph,
    ) -> None:
        """Initialise with an ontology graph and SHACL shapes graph."""
        self._ontology = ontology
        self._shapes = shapes

    @classmethod
    def from_bundled_static(cls) -> LinkedDataValidationService:
        """Create a service from the bundled ontology and shapes files."""
        ontology, shapes = _get_bundled_graphs()
        return cls(ontology=ontology, shapes=shapes)

    def validate(self, data: dict) -> LinkedDataValidationResult:
        """
        Validate a LinkedDataEnhancement's data field.

        Validates:
        1. JSON-LD expansion succeeds and produces a non-empty graph.
        2. The expanded data can be converted to an rdflib graph.
        3. No URIs in the data contain unencoded commas.
        4. The data conforms to the SHACL shapes.
        """
        errors: list[str] = []

        # Step 1: JSON-LD expansion
        try:
            expanded = jsonld.expand(data)
        except JsonLdError as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"JSON-LD expansion failed: {exc}"],
            )

        if not expanded:
            return LinkedDataValidationResult(
                conforms=False,
                errors=["JSON-LD expansion produced an empty graph."],
            )

        # Step 2: Convert expanded JSON-LD to an rdflib graph
        try:
            data_graph = Graph()
            data_graph.parse(
                data=jsonld.to_rdf(data, {"format": "application/n-quads"}),
                format="nquads",
            )
        except (JsonLdError, ValueError) as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"Failed to convert JSON-LD to RDF graph: {exc}"],
            )

        # Step 3: Reject URIs containing unencoded commas
        comma_errors = _validate_no_comma_uris(data_graph)
        if comma_errors:
            return LinkedDataValidationResult(conforms=False, errors=comma_errors)

        # Step 4: SHACL validation
        try:
            conforms, _graph, results_text = shacl_validate(
                data_graph,
                shacl_graph=self._shapes,
                ont_graph=self._ontology,
                inference="none",
                abort_on_first=False,
            )
        except ReportableRuntimeError as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"SHACL validation error: {exc}"],
            )

        if not conforms:
            errors.append(f"SHACL validation failed:\n{results_text}")

        return LinkedDataValidationResult(
            conforms=len(errors) == 0,
            errors=errors,
        )


def _validate_no_comma_uris(data_graph: Graph) -> list[str]:
    """Reject URIs containing unencoded commas."""
    errors: list[str] = []
    seen: set[str] = set()
    for s, p, o in data_graph:
        for node in (s, p, o):
            if isinstance(node, URIRef):
                uri = str(node)
                if "," in uri and uri not in seen:
                    seen.add(uri)
                    errors.append(f"URI contains unencoded comma: '{uri}'")
    return errors
