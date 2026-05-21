"""Integration tests for the `/references/search/facets/` endpoint."""

from collections.abc import AsyncGenerator
from uuid import uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.api.exception_handlers import (
    es_exception_handler,
    parse_error_exception_handler,
)
from app.core.exceptions import ESQueryError, ParseError
from app.domain.references import routes as references
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import Visibility

pytestmark = pytest.mark.usefixtures("session")


CONCEPT_A = "https://vocab.example.org/A"
CONCEPT_B = "https://vocab.example.org/B"
CONCEPT_C = "https://vocab.example.org/C"


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application instance for testing."""
    app = FastAPI(
        exception_handlers={
            ESQueryError: es_exception_handler,
            ParseError: parse_error_exception_handler,
        }
    )
    app.include_router(references.reference_router, prefix="/v1")
    return app


@pytest.fixture
async def client(
    app: FastAPI,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client for the FastAPI application."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def facet_references(es_client: AsyncElasticsearch) -> None:
    """
    Index references with known `linked_data_concepts` for facet counting.

    Indexing ReferenceDocument directly (rather than via factories +
    projections) keeps the test focused on the aggregation behaviour.

    Layout:
      - doc 1 (climate): A, B
      - doc 2 (climate): A
      - doc 3 (medical): A, C
      - doc 4 (medical): B
      - doc 5 (medical): (no concepts)

    Expected concept counts unrestricted: A=3, B=2, C=1
    Expected concept counts for `q=climate`:    A=2, B=1
    """
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Climate adaptation strategies",
            linked_data_concepts=[CONCEPT_A, CONCEPT_B],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Climate modelling primer",
            linked_data_concepts=[CONCEPT_A],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Medical imaging review",
            linked_data_concepts=[CONCEPT_A, CONCEPT_C],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Medical diagnostics overview",
            linked_data_concepts=[CONCEPT_B],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Medical training handbook",
            linked_data_concepts=None,
        ),
    ]
    for doc in docs:
        await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


async def test_concept_facet_counts_unrestricted(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """Concept buckets are returned with descending counts across all matching docs."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "*", "facet": "concepts"},
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body == {
        "facets": {
            "concepts": [
                {"uri": CONCEPT_A, "count": 3},
                {"uri": CONCEPT_B, "count": 2},
                {"uri": CONCEPT_C, "count": 1},
            ],
        }
    }


async def test_concept_facet_counts_respect_query_filter(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """A restrictive `q` narrows the set the aggregation runs over."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "climate", "facet": "concepts"},
    )
    assert response.status_code == status.HTTP_200_OK
    buckets = response.json()["facets"]["concepts"]
    assert buckets == [
        {"uri": CONCEPT_A, "count": 2},
        {"uri": CONCEPT_B, "count": 1},
    ]


async def test_concept_facet_no_matches(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """A `q` matching nothing returns an empty bucket list, not an error."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "title:nonexistent_term_xyz", "facet": "concepts"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"facets": {"concepts": []}}
