"""Client for fetching and caching vocabulary artifacts from the vocab service."""

from functools import lru_cache

import httpx
import tenacity
from cachetools import LRUCache
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from rdflib import Graph

from app.core.exceptions import ContextNotPreFetchedError
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
        :raises httpx.HTTPStatusError: On non-2xx responses after retries.
        :raises httpx.TransportError: If all retry attempts are exhausted.
        """
        if uri in self._vocabulary_cache:
            return self._vocabulary_cache[uri]

        response = await self._fetch(uri)

        graph = Graph()
        graph.parse(data=response.text, format=rdf_format)
        self._vocabulary_cache[uri] = graph
        return graph

    async def get_context(self, uri: str) -> dict:
        """
        Fetch a JSON-LD context document, returning a cached copy if available.

        :param uri: Full URI of the context document (including version).
        :return: The parsed JSON-LD context as a dict.
        :raises httpx.HTTPStatusError: On non-2xx responses after retries.
        :raises httpx.TransportError: If all retry attempts are exhausted.
        """
        if uri in self._context_cache:
            return self._context_cache[uri]

        response = await self._fetch(uri)
        doc = response.json()
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
