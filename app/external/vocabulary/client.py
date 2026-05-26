"""Client for fetching and caching vocabulary artifacts from the vocab service."""

from functools import lru_cache

import httpx
import tenacity
from cachetools import LRUCache
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from app.core.exceptions import ContextNotPreFetchedError, VocabularyFetchError
from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class VocabularyArtifactClient:
    """
    Fetches and caches vocabulary artifacts from the vocab service.

    Artifacts are keyed by their full URI (which includes a version
    component), so cached entries are valid indefinitely. The cache is
    size-bounded to prevent unbounded memory growth.
    """

    def __init__(self, cache_maxsize: int = 128) -> None:
        """Initialise the client with empty LRU caches."""
        self._vocabulary_cache: LRUCache[str, Graph] = LRUCache(maxsize=cache_maxsize)
        self._context_cache: LRUCache[str, dict] = LRUCache(maxsize=cache_maxsize)
        # Per-attribute derived-lookup caches, keyed by vocabulary URI. Populated
        # lazily on first access; eviction matches `_vocabulary_cache`'s LRU policy
        # via :meth:`_evict_derived_lookups`.
        self._concept_labels_cache: LRUCache[str, dict[str, str]] = LRUCache(
            maxsize=cache_maxsize
        )
        self._concept_schemes_cache: LRUCache[str, dict[str, str]] = LRUCache(
            maxsize=cache_maxsize
        )
        self._concept_siblings_cache: LRUCache[str, dict[str, frozenset[str]]] = (
            LRUCache(maxsize=cache_maxsize)
        )

    async def get_vocabulary(self, uri: str, rdf_format: str = "turtle") -> Graph:
        """
        Fetch a vocabulary artifact, returning a cached copy if available.

        :param uri: Full URI of the vocabulary document (including version).
        :param rdf_format: Optional RDF format hint, default is "turtle".
        :return: The parsed vocabulary as an rdflib Graph.
        :raises VocabularyFetchError: On network failure or malformed response body.
        """
        if uri in self._vocabulary_cache:
            return self._vocabulary_cache[uri]

        try:
            response = await self._fetch(uri)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            raise VocabularyFetchError(uri, repr(exc)) from exc

        try:
            graph = Graph()
            graph.parse(data=response.text, format=rdf_format)
        except Exception as exc:
            raise VocabularyFetchError(
                uri, f"Failed to parse response as {rdf_format}: {exc}"
            ) from exc

        _normalise_top_concept_triples(graph)
        self._vocabulary_cache[uri] = graph
        return graph

    async def get_context(self, uri: str) -> dict:
        """
        Fetch a JSON-LD context document, returning a cached copy if available.

        :param uri: Full URI of the context document (including version).
        :return: The parsed JSON-LD context as a dict.
        :raises VocabularyFetchError: On network failure or malformed response body.
        """
        if uri in self._context_cache:
            return self._context_cache[uri]

        try:
            response = await self._fetch(uri)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            raise VocabularyFetchError(uri, repr(exc)) from exc

        try:
            doc = response.json()
        except ValueError as exc:
            raise VocabularyFetchError(
                uri, f"Failed to parse response as JSON: {exc}"
            ) from exc

        self._context_cache[uri] = doc
        return doc

    def document_loader(self, url: str, _options: dict | None = None) -> dict:
        """
        pyld-compatible document loader that serves from the context cache.

        Since pyld is synchronous, this loader can only serve contexts that have already
        been fetched and cached.

        Contexts must be pre-fetched with :meth:`get_context` before expansion.

        :raises ContextNotPreFetchedError: If the URL is not in the cache.

        Example usage:

        .. code-block:: python
            from pyld import jsonld

            client = get_vocabulary_artifact_client()

            # Pre-fetch the context before expansion
            await client.get_context(context_url)

            expanded = jsonld.expand(
                data,
                options={
                    "documentLoader": client.document_loader,
                }
            )
        """
        if url not in self._context_cache:
            raise ContextNotPreFetchedError(url)

        return {
            "contentType": "application/ld+json",
            "contextUrl": None,
            "documentUrl": url,
            "document": self._context_cache[url],
        }

    async def get_concept_labels(self, uri: str) -> dict[str, str]:
        """
        Return ``concept URI -> skos:prefLabel`` for the named vocabulary.

        Built lazily on first access and cached per vocabulary URI. The vocabulary
        graph itself is fetched (and cached) via :meth:`get_vocabulary`.

        :param uri: Full URI of the vocabulary document.
        :return: A mapping from concept URI to its preferred label string. If a
            concept has multiple ``skos:prefLabel`` triples (e.g. multi-language),
            the last-encountered value wins.
        :raises VocabularyFetchError: If fetching the underlying vocabulary fails.
        """
        if uri in self._concept_labels_cache:
            return self._concept_labels_cache[uri]
        graph = await self.get_vocabulary(uri)
        labels = _build_concept_labels(graph)
        self._concept_labels_cache[uri] = labels
        return labels

    async def get_concept_schemes(self, uri: str) -> dict[str, str]:
        """
        Return ``concept URI -> scheme URI`` for the named vocabulary.

        Built lazily on first access and cached per vocabulary URI.

        :param uri: Full URI of the vocabulary document.
        :return: A mapping from concept URI to the URI of the ``skos:ConceptScheme``
            it belongs to (via ``skos:inScheme``).
        :raises VocabularyFetchError: If fetching the underlying vocabulary fails.
        """
        if uri in self._concept_schemes_cache:
            return self._concept_schemes_cache[uri]
        graph = await self.get_vocabulary(uri)
        schemes = _build_concept_schemes(graph)
        self._concept_schemes_cache[uri] = schemes
        return schemes

    async def get_concept_siblings(self, uri: str) -> dict[str, frozenset[str]]:
        """
        Return ``concept URI -> frozenset[sibling URIs]`` for the named vocabulary.

        Siblings are concepts that share a ``skos:broader`` parent (within a
        hierarchical scheme) or share a ``skos:ConceptScheme`` as top concepts
        (via ``skos:topConceptOf`` — ``skos:hasTopConcept`` is normalised at load
        time, see :func:`_normalise_top_concept_triples`).

        Each concept's sibling set **includes itself** so callers don't need to
        special-case the selection. Concepts with multiple ``skos:broader``
        parents have a sibling set equal to the union across all parents.

        Built lazily on first access and cached per vocabulary URI.

        :param uri: Full URI of the vocabulary document.
        :return: A mapping from each concept URI to the frozenset of its
            (self-inclusive) sibling URIs.
        :raises VocabularyFetchError: If fetching the underlying vocabulary fails.
        """
        if uri in self._concept_siblings_cache:
            return self._concept_siblings_cache[uri]
        graph = await self.get_vocabulary(uri)
        siblings = _build_concept_siblings(graph)
        self._concept_siblings_cache[uri] = siblings
        return siblings

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(httpx.TransportError),
        wait=tenacity.wait_exponential(multiplier=1, max=30),
        stop=tenacity.stop_after_attempt(3),
        reraise=True,
        before_sleep=lambda rs: logger.warning(
            "Retrying vocabulary artifact fetch.",
            attempt=rs.attempt_number,
            exc=repr(rs.outcome.exception()) if rs.outcome else None,
        ),
    )
    async def _fetch(self, uri: str) -> httpx.Response:
        """
        Fetch a document over HTTP with retries and instrumentation.

        Follows up to one redirect (API to blob storage) but rejects longer
        chains to avoid open-redirect issues.
        """
        with tracer.start_as_current_span(
            "vocabulary_artifact_client.fetch",
            attributes={"vocabulary.uri": uri},
        ):
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=1,
            ) as client:
                HTTPXClientInstrumentor().instrument_client(client)
                response = await client.get(uri)
                response.raise_for_status()
            return response


@lru_cache(maxsize=1)
def get_vocabulary_artifact_client() -> VocabularyArtifactClient:
    """Return a singleton VocabularyArtifactClient instance."""
    return VocabularyArtifactClient()


def _normalise_top_concept_triples(graph: Graph) -> None:
    """
    Add inverse ``skos:topConceptOf`` triples for every ``skos:hasTopConcept``.

    rdflib doesn't auto-derive SKOS inverse properties, and vocabularies in
    the wild (ESEA included) use both directions. Normalising at load time
    keeps the downstream lookups terse — they can pattern-match on
    ``skos:topConceptOf`` alone.
    """
    for scheme, _, concept in list(graph.triples((None, SKOS.hasTopConcept, None))):
        graph.add((concept, SKOS.topConceptOf, scheme))


def _build_concept_labels(graph: Graph) -> dict[str, str]:
    """Build ``concept URI -> skos:prefLabel`` from a SKOS graph."""
    labels: dict[str, str] = {}
    for concept, _, label in graph.triples((None, SKOS.prefLabel, None)):
        if (concept, RDF.type, SKOS.Concept) in graph:
            labels[str(concept)] = str(label)
    return labels


def _build_concept_schemes(graph: Graph) -> dict[str, str]:
    """Build ``concept URI -> skos:inScheme target`` from a SKOS graph."""
    schemes: dict[str, str] = {}
    for concept, _, scheme in graph.triples((None, SKOS.inScheme, None)):
        schemes[str(concept)] = str(scheme)
    return schemes


def _build_concept_siblings(graph: Graph) -> dict[str, frozenset[str]]:
    """
    Build ``concept URI -> frozenset[sibling URIs]`` from a SKOS graph.

    Linear in the graph size: we sweep ``skos:broader`` and ``skos:topConceptOf``
    once each to build parent-to-children and scheme-to-top-concepts indices,
    then for each concept the sibling set is the union of its co-children under
    every parent and its co-top-concepts under every scheme. Each concept's set
    includes the concept itself.
    """
    children_by_parent: dict[URIRef, set[URIRef]] = {}
    parents_by_concept: dict[URIRef, set[URIRef]] = {}
    for concept, _, parent in graph.triples((None, SKOS.broader, None)):
        if not isinstance(concept, URIRef) or not isinstance(parent, URIRef):
            continue
        children_by_parent.setdefault(parent, set()).add(concept)
        parents_by_concept.setdefault(concept, set()).add(parent)

    top_concepts_by_scheme: dict[URIRef, set[URIRef]] = {}
    schemes_by_concept: dict[URIRef, set[URIRef]] = {}
    for concept, _, scheme in graph.triples((None, SKOS.topConceptOf, None)):
        if not isinstance(concept, URIRef) or not isinstance(scheme, URIRef):
            continue
        top_concepts_by_scheme.setdefault(scheme, set()).add(concept)
        schemes_by_concept.setdefault(concept, set()).add(scheme)

    all_concepts: set[URIRef] = set(parents_by_concept) | set(schemes_by_concept)
    siblings: dict[str, frozenset[str]] = {}
    for concept in all_concepts:
        peers: set[URIRef] = {concept}
        for parent in parents_by_concept.get(concept, ()):
            peers.update(children_by_parent[parent])
        for scheme in schemes_by_concept.get(concept, ()):
            peers.update(top_concepts_by_scheme[scheme])
        siblings[str(concept)] = frozenset(str(peer) for peer in peers)
    return siblings
