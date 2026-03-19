"""Projection of LinkedDataEnhancement data into flat searchable fields."""

import json
from pathlib import Path
from typing import NamedTuple

from destiny_sdk.enhancements import LinkedDataEnhancement
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

EVREPO = Namespace("https://vocab.evidence-repository.org/")


class LinkedDataProjection(NamedTuple):
    """Result of projecting a LinkedDataEnhancement."""

    concepts: set[str]
    labels: set[str]
    evaluated_properties: set[str]


class LinkedDataProjector:
    """
    Projects LinkedDataEnhancement data into flat searchable fields.

    Operates on two RDFLib graphs:
    - A vocabulary graph (parsed once at init from a TTL file) used for
      concept validation, label lookup, and scheme-to-property mapping.
    - A data graph (parsed per-enhancement from JSON-LD) used for
      extracting codedValue triples and status checks.
    """

    def __init__(self, vocabulary_path: Path, context_path: Path) -> None:
        """Initialise the projector with vocabulary and context files."""
        self._vocab_graph = Graph()
        self._vocab_graph.parse(vocabulary_path, format="turtle")

        with context_path.open() as f:
            self._context = json.load(f)

        self._concept_labels = self._build_concept_labels()
        self._concept_schemes = self._build_concept_schemes()
        self._scheme_to_property = self._build_scheme_to_property()

    def _build_concept_labels(self) -> dict[str, str]:
        """Build concept URI -> prefLabel lookup from the vocabulary."""
        labels: dict[str, str] = {}
        for concept, _, label in self._vocab_graph.triples(
            (None, SKOS.prefLabel, None)
        ):
            if (concept, RDF.type, SKOS.Concept) in self._vocab_graph:
                labels[str(concept)] = str(label)
        return labels

    def _build_concept_schemes(self) -> dict[str, str]:
        """Build concept URI -> scheme URI lookup from the vocabulary."""
        schemes: dict[str, str] = {}
        for concept, _, scheme in self._vocab_graph.triples(
            (None, SKOS.inScheme, None)
        ):
            schemes[str(concept)] = str(scheme)
        return schemes

    def _build_scheme_to_property(self) -> dict[str, str]:
        """
        Build scheme URI -> property URI mapping via SPARQL.

        Joins across the OWL structure in a single query:
        ObjectProperty -> rdfs:range -> CodingAnnotation ->
        owl:Restriction(onProperty=codedValue, allValuesFrom=ConceptClass) ->
        Concept(type=ConceptClass) -> skos:inScheme -> Scheme.

        TODO(taxonomy-builder#171): simplify once valueScheme triples are added.
        """
        results = self._vocab_graph.query(
            """
            SELECT ?scheme ?prop WHERE {
                ?prop a owl:ObjectProperty ;
                      rdfs:range ?ann .
                ?ann rdfs:subClassOf evrepo:CodingAnnotation ;
                     rdfs:subClassOf [
                         owl:onProperty evrepo:codedValue ;
                         owl:allValuesFrom ?cls
                     ] .
                ?concept a ?cls ;
                         skos:inScheme ?scheme .
            }
            """
        )
        return {str(row.scheme): str(row.prop) for row in results}

    def project(self, enhancement: LinkedDataEnhancement) -> LinkedDataProjection:
        """Extract concepts, labels, and evaluated properties."""
        data_with_context = {
            **enhancement.data,
            "@context": self._context["@context"],
        }

        data_graph = Graph()
        data_graph.parse(data=json.dumps(data_with_context), format="json-ld")

        concepts: set[str] = set()
        labels: set[str] = set()
        evaluated_properties: set[str] = set()

        for node, _, value in data_graph.triples((None, EVREPO.codedValue, None)):
            if not isinstance(value, URIRef):
                continue

            concept_uri = str(value)

            if (value, RDF.type, SKOS.Concept) not in self._vocab_graph:
                continue

            status = self._get_status(data_graph, node)

            if status == EVREPO.coded or status is None:
                concepts.add(concept_uri)
                label = self._concept_labels.get(concept_uri)
                if label is not None:
                    labels.add(label)

            scheme_uri = self._concept_schemes.get(concept_uri)
            if scheme_uri is not None:
                prop_uri = self._scheme_to_property.get(scheme_uri)
                if prop_uri is not None:
                    evaluated_properties.add(prop_uri)

        return LinkedDataProjection(
            concepts=concepts,
            labels=labels,
            evaluated_properties=evaluated_properties,
        )

    @staticmethod
    def _get_status(data_graph: Graph, node: URIRef) -> URIRef | None:
        """Get the evrepo:status of a node in the data graph."""
        for _, _, status in data_graph.triples((node, EVREPO.status, None)):
            if isinstance(status, URIRef):
                return status
        return None
