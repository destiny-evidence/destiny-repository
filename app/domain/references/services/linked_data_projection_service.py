"""Projection of LinkedDataEnhancement data into flat searchable fields."""

import json
from dataclasses import dataclass

from destiny_sdk.enhancements import LinkedDataEnhancement
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

from app.domain.references.models.models import LinkedDataProjection
from app.domain.references.services.world_bank_regions import regions_for
from app.external.vocabulary.client import VocabularyArtifactClient

EVREPO = Namespace("https://vocab.evidence-repository.org/")
ESEA = Namespace("https://vocab.esea.education/")

# Vocabulary properties whose StringCodingAnnotation values are ISO 3166-1
# alpha-2 country codes. New vocabularies that introduce a country property
# must register it here for the values to become searchable.
_COUNTRY_PROPERTIES: frozenset[URIRef] = frozenset({ESEA.country})


@dataclass(frozen=True)
class _LoadedVocabulary:
    """A parsed vocabulary with pre-built lookups."""

    graph: Graph
    concept_labels: dict[str, str]
    concept_schemes: dict[str, str]
    scheme_to_property: dict[str, str]
    unwrapped_concept_properties: dict[str, str]


class LinkedDataProjectionService:
    """
    Projects LinkedDataEnhancement data into flat searchable fields.

    Vocabularies and contexts are resolved through a :class:`VocabularyClient`.
    Derived lookups (concept labels, scheme mappings) are cached per vocabulary URI.
    """

    def __init__(self, vocabulary_client: VocabularyArtifactClient) -> None:
        """Initialise with a vocabulary client and empty lookup caches."""
        self._vocabulary_client = vocabulary_client
        self._vocabularies: dict[str, _LoadedVocabulary] = {}

    async def project(self, enhancement: LinkedDataEnhancement) -> LinkedDataProjection:
        """Extract concepts, labels, evaluated properties, and countries."""
        vocab = await self._get_vocabulary(str(enhancement.vocabulary_uri))
        context_uri = enhancement.data.get("@context")
        if context_uri is None:
            msg = "Enhancement data is missing @context"
            raise ValueError(msg)
        context = await self._vocabulary_client.get_context(str(context_uri))

        # rdflib's JSON-LD parser cannot resolve context URIs itself, so we
        # inject the fetched context object into the data before parsing.
        data_with_context = {
            **enhancement.data,
            "@context": context["@context"],
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

            if (value, RDF.type, SKOS.Concept) not in vocab.graph:
                continue

            status = self._get_status(data_graph, node)

            if status == EVREPO.coded or status is None:
                concepts.add(concept_uri)
                label = vocab.concept_labels.get(concept_uri)
                if label is not None:
                    labels.add(label)

            scheme_uri = vocab.concept_schemes.get(concept_uri)
            if scheme_uri is not None:
                prop_uri = vocab.scheme_to_property.get(scheme_uri)
                if prop_uri is not None:
                    evaluated_properties.add(prop_uri)

        _project_unwrapped_concept_properties(
            data_graph, vocab, concepts, labels, evaluated_properties
        )

        countries = self._extract_countries(data_graph)
        return LinkedDataProjection(
            concepts=concepts,
            labels=labels,
            evaluated_properties=evaluated_properties,
            countries=countries,
            country_wb_regions=regions_for(countries),
        )

    def _extract_countries(self, data_graph: Graph) -> set[str]:
        """Extract ISO country codes from registered country-typed properties."""
        countries: set[str] = set()
        for country_property in _COUNTRY_PROPERTIES:
            for _, _, annotation in data_graph.triples((None, country_property, None)):
                status = self._get_status(data_graph, annotation)
                if status not in (EVREPO.coded, None):
                    continue
                for _, _, value in data_graph.triples(
                    (annotation, EVREPO.codedValue, None)
                ):
                    if isinstance(value, Literal):
                        code = str(value).strip().upper()
                        if code:
                            countries.add(code)
        return countries

    # -- vocabulary resolution with derived-lookup caching ---------------------

    async def _get_vocabulary(self, uri: str) -> _LoadedVocabulary:
        """Return cached derived lookups for *uri*, building on first access."""
        if uri not in self._vocabularies:
            graph = await self._vocabulary_client.get_vocabulary(uri)
            self._vocabularies[uri] = _LoadedVocabulary(
                graph=graph,
                concept_labels=self._build_concept_labels(graph),
                concept_schemes=self._build_concept_schemes(graph),
                scheme_to_property=self._build_scheme_to_property(graph),
                unwrapped_concept_properties=self._build_unwrapped_concept_properties(
                    graph
                ),
            )
        return self._vocabularies[uri]

    @staticmethod
    def _get_status(data_graph: Graph, node: URIRef) -> URIRef | None:
        """Get the evrepo:status of a node in the data graph."""
        for _, _, status in data_graph.triples((node, EVREPO.status, None)):
            if isinstance(status, URIRef):
                return status
        return None

    # -- vocabulary lookup builders --------------------------------------------

    @staticmethod
    def _build_concept_labels(graph: Graph) -> dict[str, str]:
        """Build concept URI -> prefLabel lookup from the vocabulary."""
        labels: dict[str, str] = {}
        for concept, _, label in graph.triples((None, SKOS.prefLabel, None)):
            if (concept, RDF.type, SKOS.Concept) in graph:
                labels[str(concept)] = str(label)
        return labels

    @staticmethod
    def _build_concept_schemes(graph: Graph) -> dict[str, str]:
        """Build concept URI -> scheme URI lookup from the vocabulary."""
        schemes: dict[str, str] = {}
        for concept, _, scheme in graph.triples((None, SKOS.inScheme, None)):
            schemes[str(concept)] = str(scheme)
        return schemes

    @staticmethod
    def _build_scheme_to_property(graph: Graph) -> dict[str, str]:
        """
        Build scheme URI -> property URI mapping via SPARQL.

        Joins across the OWL structure in a single query:
        ObjectProperty -> rdfs:range -> CodingAnnotation ->
        owl:Restriction(onProperty=codedValue, allValuesFrom=ConceptClass) ->
        Concept(type=ConceptClass) -> skos:inScheme -> Scheme.

        TODO(taxonomy-builder#171): simplify once valueScheme triples are added.
        """
        results = graph.query(
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

    @staticmethod
    def _build_unwrapped_concept_properties(graph: Graph) -> dict[str, str]:
        """
        Build property URI -> scheme URI mapping for unwrapped concept references.

        "Unwrapped" describes the data shape: the value is a direct concept
        reference at the property's slot, with no CodingAnnotation envelope.
        We discover these properties via their concept-typed range: either
        ``skos:ConceptScheme`` directly, or a class ``subClassOf skos:Concept``
        joined to a scheme via concept instances.
        """
        results = graph.query(
            """
            SELECT DISTINCT ?prop ?scheme WHERE {
                ?prop a owl:ObjectProperty ;
                      rdfs:range ?range .
                {
                    ?range a skos:ConceptScheme .
                    BIND(?range AS ?scheme)
                }
                UNION
                {
                    ?range rdfs:subClassOf+ skos:Concept .
                    FILTER(?range != skos:Concept)
                    ?concept a ?range ;
                             skos:inScheme ?scheme .
                }
            }
            """
        )
        return {str(row.prop): str(row.scheme) for row in results}


def _project_unwrapped_concept_properties(
    data_graph: Graph,
    vocab: _LoadedVocabulary,
    concepts: set[str],
    labels: set[str],
    evaluated_properties: set[str],
) -> None:
    """
    Project values for properties discovered by ``_build_unwrapped_concept_properties``.

    Without a CodingAnnotation wrapper there is no provenance, so any present
    value is treated as coded.
    """
    for prop_uri_str in vocab.unwrapped_concept_properties:
        predicate = URIRef(prop_uri_str)
        for _, _, value in data_graph.triples((None, predicate, None)):
            if not isinstance(value, URIRef):
                continue
            if (value, RDF.type, SKOS.Concept) not in vocab.graph:
                continue
            concept_uri = str(value)
            concepts.add(concept_uri)
            label = vocab.concept_labels.get(concept_uri)
            if label is not None:
                labels.add(label)
            evaluated_properties.add(prop_uri_str)
