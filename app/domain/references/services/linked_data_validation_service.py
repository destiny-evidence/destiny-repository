"""Service for validating LinkedDataEnhancements against an OWL/SKOS ontology."""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, Field
from pyld import jsonld
from pyld.jsonld import JsonLdError
from pyshacl import validate as shacl_validate
from pyshacl.errors import ReportableRuntimeError
from rdflib import OWL, RDF, RDFS, SKOS, Graph, URIRef

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
    """Validates LinkedDataEnhancements using JSON-LD expansion, SHACL, and SKOS."""

    def __init__(
        self,
        ontology: Graph,
        shapes: Graph,
    ) -> None:
        """Initialise with an ontology graph and SHACL shapes graph."""
        self._ontology = ontology
        self._shapes = shapes
        self._concept_uris = _extract_concept_uris(ontology)

    @classmethod
    def from_bundled_static(cls) -> LinkedDataValidationService:
        """Create a service from the bundled ontology and shapes files."""
        ontology, shapes = _get_bundled_graphs()
        return cls(ontology=ontology, shapes=shapes)

    def validate(self, data: dict) -> LinkedDataValidationResult:
        """
        Validate a LinkedDataEnhancement's data field.

        Runs JSON-LD expansion, SHACL validation, and SKOS concept checking.
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

        # Step 3: SHACL validation
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

        # Step 4: SKOS concept URI validation
        concept_errors = self._validate_concept_uris(data_graph)
        errors.extend(concept_errors)

        return LinkedDataValidationResult(
            conforms=len(errors) == 0,
            errors=errors,
        )

    def _validate_concept_uris(self, data_graph: Graph) -> list[str]:
        """Check that concept URI references in the data exist in the ontology."""
        errors: list[str] = []

        # Find properties whose range is a subclass of skos:Concept
        concept_range_properties: set[URIRef] = set()
        for prop in self._ontology.subjects(RDF.type, OWL.ObjectProperty):
            if not isinstance(prop, URIRef):
                continue
            for range_cls in self._ontology.objects(prop, RDFS.range):
                if isinstance(range_cls, URIRef) and _is_concept_class(
                    range_cls, self._ontology
                ):
                    concept_range_properties.add(prop)

        for prop in concept_range_properties:
            for _subj, _pred, obj in data_graph.triples((None, prop, None)):
                if isinstance(obj, URIRef) and str(obj) not in self._concept_uris:
                    errors.append(
                        f"Unknown concept URI '{obj}' used with property '{prop}'."
                    )

        return errors


def _extract_concept_uris(ontology: Graph) -> set[str]:
    """Extract all SKOS Concept URIs from the ontology."""
    concept_uris: set[str] = set()
    for concept in ontology.subjects(RDF.type, SKOS.Concept):
        if isinstance(concept, URIRef):
            concept_uris.add(str(concept))
    return concept_uris


def _is_concept_class(cls: URIRef, ontology: Graph) -> bool:
    """Check if a class is or is a subclass of skos:Concept."""
    if cls == SKOS.Concept:
        return True
    return any(
        parent == SKOS.Concept for parent in ontology.objects(cls, RDFS.subClassOf)
    )
