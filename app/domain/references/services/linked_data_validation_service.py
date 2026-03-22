"""Service for validating LinkedDataEnhancements against an OWL/SKOS ontology."""

import functools

from pydantic import BaseModel, Field
from pyld import jsonld
from pyld.jsonld import JsonLdError
from pyshacl import validate as shacl_validate
from pyshacl.errors import ReportableRuntimeError
from rdflib import Graph, URIRef

from app.core.config import get_settings

_SHAPES_PATH = get_settings().project_root / "app" / "static" / "evrepo-core-shapes.ttl"


@functools.cache
def _get_bundled_shapes() -> Graph:
    """Return the bundled SHACL shapes graph, parsing on first call."""
    shapes = Graph()
    shapes.parse(str(_SHAPES_PATH), format="turtle")
    return shapes


class LinkedDataValidationResult(BaseModel):
    """Result of validating a LinkedDataEnhancement."""

    conforms: bool
    errors: list[str] = Field(default_factory=list)


class LinkedDataValidationService:
    """Validates LinkedDataEnhancements using JSON-LD expansion and SHACL."""

    def __init__(self, ontology: Graph | None = None) -> None:
        """Initialise with the bundled SHACL shapes and optional ontology."""
        self._shapes = _get_bundled_shapes()
        self._ontology = ontology

    def _resolve_ontology(
        self,
        vocabulary_uri: str,  # noqa: ARG002
    ) -> Graph | None:
        """
        Resolve a vocabulary URI to an ontology graph.

        Returns None if the vocabulary is not yet available.
        """
        # TODO(Adam): resolve ontology graph from vocabulary_uri
        # https://github.com/destiny-evidence/destiny-repository/issues/593
        return None

    def validate(  # noqa: PLR0911
        self, data: dict, vocabulary_uri: str
    ) -> LinkedDataValidationResult | None:
        """
        Validate a LinkedDataEnhancement's data field.

        Returns None if the vocabulary is not yet available.

        Validates:
        1. JSON-LD expansion succeeds and produces a non-empty graph.
        2. The expanded data can be converted to an rdflib graph.
        3. No URIs in the data contain unencoded commas.
        4. The data conforms to the SHACL shapes.
        """
        ontology = self._ontology or self._resolve_ontology(vocabulary_uri)
        if ontology is None:
            return None

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
                ont_graph=ontology,
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
            conforms=conforms,
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
