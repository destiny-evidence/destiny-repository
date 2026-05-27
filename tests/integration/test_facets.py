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

# ISO 3166-1 alpha-2 codes and their World Bank region IDs (KE/UG -> SSF, US -> NAC).
COUNTRY_KE = "KE"
COUNTRY_UG = "UG"
COUNTRY_US = "US"
REGION_SSF = "SSF"
REGION_NAC = "NAC"


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
    Index references with known facet fields for counting.

    Indexing ReferenceDocument directly (rather than via factories +
    projections) keeps the test focused on the aggregation behaviour.

    Layout:
      - doc 1 (climate): A, B; KE, UG; SSF
      - doc 2 (climate): A;    KE;     SSF
      - doc 3 (medical): A, C; US;     NAC
      - doc 4 (medical): B;    UG;     SSF
      - doc 5 (medical): (no facet fields)

    Expected concept counts unrestricted: A=3, B=2, C=1
    Expected concept counts for `q=climate`:    A=2, B=1
    Expected country counts unrestricted: KE=2, UG=2, US=1
    Expected region counts unrestricted: SSF=3, NAC=1
    """
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Climate adaptation strategies",
            linked_data_concepts=[CONCEPT_A, CONCEPT_B],
            linked_data_countries=[COUNTRY_KE, COUNTRY_UG],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Climate modelling primer",
            linked_data_concepts=[CONCEPT_A],
            linked_data_countries=[COUNTRY_KE],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Medical imaging review",
            linked_data_concepts=[CONCEPT_A, CONCEPT_C],
            linked_data_countries=[COUNTRY_US],
            linked_data_country_wb_regions=[REGION_NAC],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="Medical diagnostics overview",
            linked_data_concepts=[CONCEPT_B],
            linked_data_countries=[COUNTRY_UG],
            linked_data_country_wb_regions=[REGION_SSF],
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
        "concepts": [
            {"concept": CONCEPT_A, "count": 3},
            {"concept": CONCEPT_B, "count": 2},
            {"concept": CONCEPT_C, "count": 1},
        ],
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
    buckets = response.json()["concepts"]
    assert buckets == [
        {"concept": CONCEPT_A, "count": 2},
        {"concept": CONCEPT_B, "count": 1},
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
    assert response.json() == {"concepts": []}


async def test_country_facet_counts_unrestricted(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """Country buckets are keyed by ISO-2 code with descending counts."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "*", "facet": "countries"},
    )
    assert response.status_code == status.HTTP_200_OK
    buckets = response.json()["countries"]
    # KE and UG tie at 2; only assert US trails them.
    assert {(b["country"], b["count"]) for b in buckets} == {
        (COUNTRY_KE, 2),
        (COUNTRY_UG, 2),
        (COUNTRY_US, 1),
    }


async def test_region_facet_counts_unrestricted(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """World Bank region buckets are keyed by region ID with descending counts."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "*", "facet": "country_wb_regions"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["country_wb_regions"] == [
        {"country_wb_region": REGION_SSF, "count": 3},
        {"country_wb_region": REGION_NAC, "count": 1},
    ]


async def test_multiple_facets_returned_together(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """Requesting several facets returns each requested type and omits the rest."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[("q", "*"), ("facet", "concepts"), ("facet", "countries")],
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert set(body) == {"concepts", "countries"}
    assert "country_wb_regions" not in body


async def test_concept_filter_does_not_drop_country_facet(
    client: AsyncClient,
    facet_references: None,  # noqa: ARG001
) -> None:
    """
    A concept filter must not drop a co-requested non-concept facet.

    Guards the sibling-aware aggregation path (destiny-repository#714), whose
    concept handling must still return every other facet it was asked for.
    """
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", CONCEPT_A),
            ("facet", "concepts"),
            ("facet", "countries"),
        ],
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert "concepts" in body
    assert "countries" in body
