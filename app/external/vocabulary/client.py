"""Client for fetching and caching vocabulary artifacts from the vocab service."""

from functools import lru_cache

import httpx
import tenacity
from async_lru import alru_cache
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

    @alru_cache(maxsize=128)
    async def get_concept_labels(self, uri: str) -> dict[str, str]:
        """Concept URI -> skos:prefLabel for the vocabulary."""
        return _build_concept_labels(await self.get_vocabulary(uri))

    @alru_cache(maxsize=128)
    async def get_concept_schemes(self, uri: str) -> dict[str, str]:
        """Concept URI -> skos:inScheme target for the vocabulary."""
        return _build_concept_schemes(await self.get_vocabulary(uri))

    @alru_cache(maxsize=128)
    async def get_concept_siblings(self, uri: str) -> dict[str, frozenset[str]]:
        """Concept URI -> sibling set (self-inclusive) for the vocabulary."""
        return _build_concept_siblings(await self.get_vocabulary(uri))

    @alru_cache(maxsize=128)
    async def get_scheme_members(self, uri: str) -> dict[str, frozenset[str]]:
        """Concept-scheme URI -> member concept URIs (all depths) for the vocabulary."""
        return _build_scheme_members(await self.get_vocabulary(uri))

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


def _build_concept_labels(graph: Graph) -> dict[str, str]:
    labels: dict[str, str] = {}
    for concept, _, label in graph.triples((None, SKOS.prefLabel, None)):
        if (concept, RDF.type, SKOS.Concept) in graph:
            labels[str(concept)] = str(label)
    return labels


def _build_concept_schemes(graph: Graph) -> dict[str, str]:
    return {
        str(concept): str(scheme)
        for concept, _, scheme in graph.triples((None, SKOS.inScheme, None))
    }


def _build_concept_siblings(graph: Graph) -> dict[str, frozenset[str]]:
    children_by_parent: dict[URIRef, set[URIRef]] = {}
    parents_by_concept: dict[URIRef, set[URIRef]] = {}
    for concept, _, parent in graph.triples((None, SKOS.broader, None)):
        if not isinstance(concept, URIRef) or not isinstance(parent, URIRef):
            continue
        children_by_parent.setdefault(parent, set()).add(concept)
        parents_by_concept.setdefault(concept, set()).add(parent)

    top_concepts_by_scheme: dict[URIRef, set[URIRef]] = {}
    schemes_by_concept: dict[URIRef, set[URIRef]] = {}
    # Vocabularies in the wild use both directions; rdflib doesn't derive
    # SKOS inverses, so we read each direction explicitly.
    top_concept_triples = list(graph.triples((None, SKOS.topConceptOf, None))) + [
        (concept, None, scheme)
        for scheme, _, concept in graph.triples((None, SKOS.hasTopConcept, None))
    ]
    for concept, _, scheme in top_concept_triples:
        if not isinstance(concept, URIRef) or not isinstance(scheme, URIRef):
            continue
        top_concepts_by_scheme.setdefault(scheme, set()).add(concept)
        schemes_by_concept.setdefault(concept, set()).add(scheme)

    # Concepts declared only via skos:inScheme (no broader, no topConceptOf)
    # are treated as implicit top concepts of their scheme — otherwise they'd
    # be invisible to sibling lookups despite being valid SKOS.
    for concept, _, scheme in graph.triples((None, SKOS.inScheme, None)):
        if not isinstance(concept, URIRef) or not isinstance(scheme, URIRef):
            continue
        if concept in parents_by_concept or concept in schemes_by_concept:
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


def _build_scheme_members(graph: Graph) -> dict[str, frozenset[str]]:
    """
    Map each concept-scheme URI to the full set of its member concept URIs.

    Membership comes from explicit assertions (``skos:inScheme``,
    ``skos:topConceptOf``, ``skos:hasTopConcept``); a concept with no assertion of its
    own inherits its ``skos:broader`` ancestor's scheme(s), so descendants that omit
    ``inScheme`` are still captured. Concepts that declare their own scheme are never
    reassigned, so a ``broader`` edge across scheme boundaries does not leak members.
    """
    explicit_schemes: dict[URIRef, set[URIRef]] = {}

    def _assert(concept: object, scheme: object) -> None:
        if isinstance(concept, URIRef) and isinstance(scheme, URIRef):
            explicit_schemes.setdefault(concept, set()).add(scheme)

    for concept, _, scheme in graph.triples((None, SKOS.inScheme, None)):
        _assert(concept, scheme)
    for concept, _, scheme in graph.triples((None, SKOS.topConceptOf, None)):
        _assert(concept, scheme)
    for scheme, _, concept in graph.triples((None, SKOS.hasTopConcept, None)):
        _assert(concept, scheme)

    parents_by_concept: dict[URIRef, set[URIRef]] = {}
    for concept, _, parent in graph.triples((None, SKOS.broader, None)):
        if isinstance(concept, URIRef) and isinstance(parent, URIRef):
            parents_by_concept.setdefault(concept, set()).add(parent)

    def schemes_for(concept: URIRef, seen: set[URIRef]) -> set[URIRef]:
        if concept in explicit_schemes:
            return explicit_schemes[concept]
        if concept in seen:
            return set()
        seen.add(concept)
        inherited: set[URIRef] = set()
        for parent in parents_by_concept.get(concept, ()):
            inherited |= schemes_for(parent, seen)
        return inherited

    members: dict[str, set[str]] = {}
    for concept in set(explicit_schemes) | set(parents_by_concept):
        for scheme in schemes_for(concept, set()):
            members.setdefault(str(scheme), set()).add(str(concept))
    return {scheme: frozenset(uris) for scheme, uris in members.items()}
