"""Tests for VocabularyArtifactClient."""

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock

from app.core.exceptions import VocabularyFetchError
from app.external.vocabulary.client import (
    ContextNotPreFetchedError,
    VocabularyArtifactClient,
)

SAMPLE_TURTLE = """\
@prefix ex: <http://example.org/> .
ex:Thing a ex:Class .
"""

SAMPLE_CONTEXT = {"@context": {"ex": "http://example.org/"}}

VOCAB_URI = "https://vocab.example.org/vocabulary/v1"
CONTEXT_URI = "https://vocab.example.org/context/v1.jsonld"

# SKOS vocab covering the four shapes the lookups have to handle:
#   - hierarchical scheme: Biology -> Botany, Zoology, Microbiology
#   - flat scheme using skos:topConceptOf:        Africa, Asia
#   - flat scheme using skos:hasTopConcept:       Apple, Pear
#   - flat scheme using only skos:inScheme:       English, Spanish
#   - multi-parented concept under two parents:   Quantum (under both Physics & Math)
SKOS_TURTLE = """\
@prefix ex:   <http://example.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Topics a skos:ConceptScheme .

ex:Biology  a skos:Concept ; skos:inScheme ex:Topics ; skos:prefLabel "Biology" ;
            skos:topConceptOf ex:Topics .
ex:Chemistry a skos:Concept ; skos:inScheme ex:Topics ; skos:prefLabel "Chemistry" ;
             skos:topConceptOf ex:Topics .

ex:Botany       a skos:Concept ; skos:inScheme ex:Topics ;
                skos:prefLabel "Botany" ; skos:broader ex:Biology .
ex:Zoology      a skos:Concept ; skos:inScheme ex:Topics ;
                skos:prefLabel "Zoology" ; skos:broader ex:Biology .
ex:Microbiology a skos:Concept ; skos:inScheme ex:Topics ;
                skos:prefLabel "Microbiology" ; skos:broader ex:Biology .

ex:Regions a skos:ConceptScheme .
ex:Africa a skos:Concept ; skos:inScheme ex:Regions ; skos:prefLabel "Africa" ;
          skos:topConceptOf ex:Regions .
ex:Asia   a skos:Concept ; skos:inScheme ex:Regions ; skos:prefLabel "Asia" ;
          skos:topConceptOf ex:Regions .

ex:Fruits a skos:ConceptScheme ;
          skos:hasTopConcept ex:Apple , ex:Pear .
ex:Apple a skos:Concept ; skos:inScheme ex:Fruits ; skos:prefLabel "Apple" .
ex:Pear  a skos:Concept ; skos:inScheme ex:Fruits ; skos:prefLabel "Pear" .

ex:Languages a skos:ConceptScheme .
ex:English a skos:Concept ; skos:inScheme ex:Languages ; skos:prefLabel "English" .
ex:Spanish a skos:Concept ; skos:inScheme ex:Languages ; skos:prefLabel "Spanish" .

ex:Sciences a skos:ConceptScheme .
ex:Physics a skos:Concept ; skos:inScheme ex:Sciences ; skos:prefLabel "Physics" ;
           skos:topConceptOf ex:Sciences .
ex:Mathematics a skos:Concept ; skos:inScheme ex:Sciences ;
               skos:prefLabel "Mathematics" ;
               skos:topConceptOf ex:Sciences .
ex:Quantum a skos:Concept ; skos:inScheme ex:Sciences ; skos:prefLabel "Quantum" ;
           skos:broader ex:Physics , ex:Mathematics .
"""


@pytest.fixture
def client() -> VocabularyArtifactClient:
    return VocabularyArtifactClient()


@pytest_asyncio.fixture
async def skos_client(
    client: VocabularyArtifactClient, httpx_mock: HTTPXMock
) -> VocabularyArtifactClient:
    """Client primed to serve the SKOS sample vocabulary at VOCAB_URI."""
    httpx_mock.add_response(
        url=VOCAB_URI,
        text=SKOS_TURTLE,
        headers={"content-type": "text/turtle"},
    )
    return client


class TestGetVocabulary:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_turtle(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(
            url=VOCAB_URI,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        graph = await client.get_vocabulary(VOCAB_URI)

        assert len(graph) > 0

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(
            url=VOCAB_URI,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        first = await client.get_vocabulary(VOCAB_URI)
        second = await client.get_vocabulary(VOCAB_URI)

        assert first is second
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_different_uris_cached_separately(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        uri_v1 = "https://vocab.example.org/vocabulary/v1"
        uri_v2 = "https://vocab.example.org/vocabulary/v2"

        httpx_mock.add_response(
            url=uri_v1,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )
        httpx_mock.add_response(
            url=uri_v2,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        await client.get_vocabulary(uri_v1)
        await client.get_vocabulary(uri_v2)

        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.asyncio
    async def test_http_error_raises(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=VOCAB_URI, status_code=404)

        with pytest.raises(VocabularyFetchError) as exc_info:
            await client.get_vocabulary(VOCAB_URI)

        assert exc_info.value.uri == VOCAB_URI
        assert exc_info.value.__cause__ is not None

    @pytest.mark.asyncio
    async def test_failed_fetch_not_cached(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=VOCAB_URI, status_code=500)

        with pytest.raises(VocabularyFetchError):
            await client.get_vocabulary(VOCAB_URI)

        # Subsequent call should retry, not return a cached error
        httpx_mock.add_response(
            url=VOCAB_URI,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        graph = await client.get_vocabulary(VOCAB_URI)
        assert len(graph) > 0

    @pytest.mark.asyncio
    async def test_malformed_body_raises(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=VOCAB_URI, text="this is not valid turtle {{{}}")

        with pytest.raises(VocabularyFetchError) as exc_info:
            await client.get_vocabulary(VOCAB_URI)

        assert "Failed to parse" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retries_on_transport_error(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        httpx_mock.add_response(
            url=VOCAB_URI,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        graph = await client.get_vocabulary(VOCAB_URI)
        assert len(graph) > 0
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.asyncio
    async def test_follows_single_redirect(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        blob_url = "https://blob.storage.example.org/vocabulary/v1.ttl"
        httpx_mock.add_response(
            url=VOCAB_URI,
            status_code=302,
            headers={"location": blob_url},
        )
        httpx_mock.add_response(
            url=blob_url,
            text=SAMPLE_TURTLE,
            headers={"content-type": "text/turtle"},
        )

        graph = await client.get_vocabulary(VOCAB_URI)
        assert len(graph) > 0
        assert len(httpx_mock.get_requests()) == 2


class TestGetContext:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_json(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, json=SAMPLE_CONTEXT)

        doc = await client.get_context(CONTEXT_URI)

        assert doc == SAMPLE_CONTEXT

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, json=SAMPLE_CONTEXT)

        first = await client.get_context(CONTEXT_URI)
        second = await client.get_context(CONTEXT_URI)

        assert first is second
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_http_error_raises(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, status_code=404)

        with pytest.raises(VocabularyFetchError) as exc_info:
            await client.get_context(CONTEXT_URI)

        assert exc_info.value.uri == CONTEXT_URI
        assert exc_info.value.__cause__ is not None

    @pytest.mark.asyncio
    async def test_failed_fetch_not_cached(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, status_code=500)

        with pytest.raises(VocabularyFetchError):
            await client.get_context(CONTEXT_URI)

        httpx_mock.add_response(url=CONTEXT_URI, json=SAMPLE_CONTEXT)

        doc = await client.get_context(CONTEXT_URI)
        assert doc == SAMPLE_CONTEXT

    @pytest.mark.asyncio
    async def test_malformed_body_raises(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, text="not json {{{")

        with pytest.raises(VocabularyFetchError) as exc_info:
            await client.get_context(CONTEXT_URI)

        assert "Failed to parse" in str(exc_info.value)


class TestDocumentLoader:
    @pytest.mark.asyncio
    async def test_returns_cached_context(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, json=SAMPLE_CONTEXT)
        await client.get_context(CONTEXT_URI)

        result = client.document_loader(CONTEXT_URI)

        assert result["document"] == SAMPLE_CONTEXT
        assert result["documentUrl"] == CONTEXT_URI
        assert result["contentType"] == "application/ld+json"
        assert result["contextUrl"] is None

    def test_raises_for_unfetched_uri(self, client: VocabularyArtifactClient):
        with pytest.raises(ContextNotPreFetchedError) as exc_info:
            client.document_loader("https://not-fetched.example.org/ctx.jsonld")

        assert exc_info.value.uri == "https://not-fetched.example.org/ctx.jsonld"


def _concept(name: str) -> str:
    return f"http://example.org/{name}"


class TestSkosDerivedLookups:
    @pytest.mark.asyncio
    async def test_concept_labels_and_schemes(
        self, skos_client: VocabularyArtifactClient
    ):
        labels = await skos_client.get_concept_labels(VOCAB_URI)
        schemes = await skos_client.get_concept_schemes(VOCAB_URI)

        assert labels[_concept("Botany")] == "Botany"
        assert schemes[_concept("Botany")] == _concept("Topics")
        assert schemes[_concept("Apple")] == _concept("Fruits")

    @pytest.mark.asyncio
    async def test_siblings_covers_broader_and_top_concept_variants(
        self, skos_client: VocabularyArtifactClient
    ):
        siblings = await skos_client.get_concept_siblings(VOCAB_URI)

        # Hierarchical (skos:broader) — set includes the concept itself.
        biology_children = frozenset(
            {_concept("Botany"), _concept("Zoology"), _concept("Microbiology")}
        )
        assert siblings[_concept("Botany")] == biology_children
        assert siblings[_concept("Microbiology")] == biology_children

        # Flat scheme via skos:topConceptOf.
        assert siblings[_concept("Biology")] == frozenset(
            {_concept("Biology"), _concept("Chemistry")}
        )

        # Flat scheme via skos:hasTopConcept (normalised to topConceptOf on load).
        assert siblings[_concept("Apple")] == frozenset(
            {_concept("Apple"), _concept("Pear")}
        )

        # Flat scheme with only skos:inScheme — treated as implicit top concepts.
        assert siblings[_concept("English")] == frozenset(
            {_concept("English"), _concept("Spanish")}
        )

        # Multi-parented: union of co-children across both parents.
        # Quantum is the only child of both Physics and Mathematics.
        assert siblings[_concept("Quantum")] == frozenset({_concept("Quantum")})
