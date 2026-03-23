"""Tests for VocabularyArtifactClient."""

import httpx
import pytest
from pytest_httpx import HTTPXMock

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


@pytest.fixture
def client() -> VocabularyArtifactClient:
    return VocabularyArtifactClient()


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

        with pytest.raises(httpx.HTTPStatusError):
            await client.get_vocabulary(VOCAB_URI)

    @pytest.mark.asyncio
    async def test_failed_fetch_not_cached(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=VOCAB_URI, status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
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

        with pytest.raises(httpx.HTTPStatusError):
            await client.get_context(CONTEXT_URI)

    @pytest.mark.asyncio
    async def test_failed_fetch_not_cached(
        self, client: VocabularyArtifactClient, httpx_mock: HTTPXMock
    ):
        httpx_mock.add_response(url=CONTEXT_URI, status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await client.get_context(CONTEXT_URI)

        httpx_mock.add_response(url=CONTEXT_URI, json=SAMPLE_CONTEXT)

        doc = await client.get_context(CONTEXT_URI)
        assert doc == SAMPLE_CONTEXT


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
