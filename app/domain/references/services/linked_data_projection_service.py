"""Projection of LinkedDataEnhancement data into flat searchable fields."""

import json
from dataclasses import dataclass
from pathlib import Path

from destiny_sdk.enhancements import LinkedDataEnhancement
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

from app.domain.references.models.models import LinkedDataProjection

EVREPO = Namespace("https://vocab.evidence-repository.org/")


# -- transitional static-file client ------------------------------------------

_STATIC_VOCAB_DIR = (
    Path(__file__).parent.parent.parent.parent / "static" / "vocab" / "esea"
)

_STATIC_VOCABULARY_PATHS: dict[str, Path] = {
    "https://vocab.esea.education/vocabulary/v1": (
        _STATIC_VOCAB_DIR / "esea-vocab.ttl"
    ),
}
_STATIC_CONTEXT_PATHS: dict[str, Path] = {
    "https://vocab.esea.education/context/v1.jsonld": (
        _STATIC_VOCAB_DIR / "esea-context.jsonld"
    ),
}


class StaticFileVocabularyClient:
    """
    Resolves vocabulary URIs to bundled static files.

    Drop-in replacement for ``VocabularyArtifactClient`` until #600 lands.
    """

    def __init__(self) -> None:
        """Initialise with empty caches."""
        self._vocabulary_cache: dict[str, Graph] = {}
        self._context_cache: dict[str, dict] = {}

    async def get_vocabulary(self, uri: str) -> Graph:
        """Return a cached vocabulary graph, loading from static files on first access."""  # noqa: E501
        if uri not in self._vocabulary_cache:
            path = _STATIC_VOCABULARY_PATHS.get(uri)
            if path is None:
                msg = f"No static vocabulary registered for URI: {uri}"
                raise ValueError(msg)
            graph = Graph()
            graph.parse(path, format="turtle")
            self._vocabulary_cache[uri] = graph
        return self._vocabulary_cache[uri]

    async def get_context(self, uri: str) -> dict:
        """Return a cached context dict, loading from static files on first access."""
        if uri not in self._context_cache:
            path = _STATIC_CONTEXT_PATHS.get(uri)
            if path is None:
                msg = f"No static context registered for URI: {uri}"
                raise ValueError(msg)
            with path.open() as f:
                self._context_cache[uri] = json.load(f)
        return self._context_cache[uri]


# -- projection service -------------------------------------------------------


@dataclass(frozen=True)
class _LoadedVocabulary:
    """A parsed vocabulary with pre-built lookups."""

    graph: Graph
    concept_labels: dict[str, str]
    concept_schemes: dict[str, str]
    scheme_to_property: dict[str, str]


class LinkedDataProjectionService:
    """
    Projects LinkedDataEnhancement data into flat searchable fields.

    Vocabularies and contexts are resolved through a :class:`VocabularyClient`.
    Derived lookups (concept labels, scheme mappings) are cached per vocabulary URI.
    """

    def __init__(self, vocabulary_client: StaticFileVocabularyClient) -> None:
        """Initialise with a vocabulary client and empty lookup caches."""
        self._vocabulary_client = vocabulary_client
        self._vocabularies: dict[str, _LoadedVocabulary] = {}

    async def project(self, enhancement: LinkedDataEnhancement) -> LinkedDataProjection:
        """Extract concepts, labels, and evaluated properties."""
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

        return LinkedDataProjection(
            concepts=concepts,
            labels=labels,
            evaluated_properties=evaluated_properties,
        )

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
