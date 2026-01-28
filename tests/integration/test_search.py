"""Integration tests for search API with complex query string scenarios."""

from collections.abc import AsyncGenerator, Callable

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
from app.domain.references.repository import ReferenceESRepository
from tests.factories import (
    AbstractContentEnhancementFactory,
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    EnhancementFactory,
    ReferenceFactory,
)

pytestmark = pytest.mark.usefixtures("session")


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
async def search_references(es_client: AsyncElasticsearch):
    """Create and index test references with various metadata and annotations."""
    references = [
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Machine Learning in Climate Science",
                        publication_year=2023,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "This study explores the application of neural networks "
                            "for predicting climate patterns and analyzing "
                            "temperature data."
                        )
                    )
                ),
                EnhancementFactory.build(
                    content=AnnotationEnhancementFactory.build(
                        annotations=[
                            BooleanAnnotationFactory.build(
                                scheme="inclusion:destiny",
                                label="relevant",
                                value=True,
                                score=0.95,
                            )
                        ]
                    )
                ),
            ]
        ),
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Deep Learning for Medical Diagnosis",
                        publication_year=2022,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "We present a comprehensive framework using convolutional "
                            "neural networks to detect diseases from medical imaging."
                        )
                    )
                ),
                EnhancementFactory.build(
                    content=AnnotationEnhancementFactory.build(
                        annotations=[
                            BooleanAnnotationFactory.build(
                                scheme="inclusion:destiny",
                                value=False,
                                score=0.3,
                            ),
                            BooleanAnnotationFactory.build(
                                scheme="classifier:taxonomy",
                                label="Outcomes/Mortality",
                                value=True,
                            ),
                        ]
                    )
                ),
            ]
        ),
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Climate Change Impact on Agriculture",
                        publication_year=2021,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "Analysis of agricultural productivity under changing "
                            "climate conditions with focus on crop yields."
                        )
                    )
                ),
                EnhancementFactory.build(
                    content=AnnotationEnhancementFactory.build(
                        annotations=[
                            BooleanAnnotationFactory.build(
                                scheme="inclusion:destiny",
                                value=True,
                                score=0.88,
                            ),
                            BooleanAnnotationFactory.build(
                                scheme="classifier:taxonomy",
                                label="Outcomes/Economic",
                                value=True,
                            ),
                        ]
                    )
                ),
            ]
        ),
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Neural Networks in Healthcare",
                        publication_year=2020,
                    )
                )
            ]
        ),
    ]

    # Add extra references for pagination testing
    references.extend(
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title=f"Pagination Test Paper {i}",
                        publication_year=2019,
                    )
                )
            ]
        )
        for i in range(25)
    )

    es_repository = ReferenceESRepository(es_client)
    for reference in references:
        await es_repository.add(reference)
    await es_client.indices.refresh(index="reference")
    return references


@pytest.mark.parametrize(
    ("params", "expected_count", "validation_fn"),
    [
        # Boolean operators
        (
            {"q": "(title:Machine OR title:Deep) AND title:Learning"},
            2,
            lambda refs: all(
                "Learning" in ref["enhancements"][0]["content"]["title"] for ref in refs
            ),
        ),
        # Wildcard with year filter and sorting
        (
            {
                "q": "title:Climat*",
                "start_year": 2020,
                "end_year": 2023,
                "sort": ["-publication_year"],
            },
            2,
            lambda refs: (
                refs[0]["enhancements"][0]["content"]["publication_year"]
                > refs[1]["enhancements"][0]["content"]["publication_year"]
            ),
        ),
        # Fuzzy matching with NOT
        (
            {"q": "title:Lerning~1 NOT title:Climate"},
            1,
            lambda refs: "Medical" in refs[0]["enhancements"][0]["content"]["title"],
        ),
        # Annotation filter: inclusion true with score threshold and sort by score
        (
            {
                "q": "title:*",
                "annotation": ["inclusion:destiny@0.8"],
                "sort": ["-inclusion_destiny"],
            },
            2,
            lambda refs: (
                refs[0]["enhancements"][0]["content"]["title"]
                == "Machine Learning in Climate Science"
            ),
        ),
        # Annotation filter: specific taxonomy label
        (
            {
                "q": "*",
                "annotation": ["classifier:taxonomy/Outcomes/Economic"],
            },
            1,
            lambda refs: "Climate" in refs[0]["enhancements"][0]["content"]["title"],
        ),
        # Query with year range and annotation filter
        (
            {
                "q": "title:Learning",
                "start_year": 2022,
                "annotation": ["inclusion:destiny@0.9"],
            },
            1,
            lambda refs: "Machine" in refs[0]["enhancements"][0]["content"]["title"],
        ),
        # Combined title and abstract search
        (
            {"q": "title:Climate AND abstract:agricultural"},
            1,
            lambda refs: (
                "Agriculture" in refs[0]["enhancements"][0]["content"]["title"]
            ),
        ),
    ],
)
async def test_query_string_with_filters(
    client: AsyncClient,
    search_references: list,  # noqa: ARG001
    params: dict,
    expected_count: int,
    validation_fn: Callable,
) -> None:
    """Test query string searches with various filters and annotations."""
    response = await client.get("/v1/references/search/", params=params)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"]["count"] == expected_count
    if expected_count > 0:
        assert validation_fn(data["references"])


async def test_pagination(
    client: AsyncClient,
    search_references: list,  # noqa: ARG001
) -> None:
    """Test pagination with query string search."""
    # Search for pagination test papers (25 total)
    response = await client.get(
        "/v1/references/search/",
        params={"q": "title:Pagination", "page": 1},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"]["count"] == 25
    assert data["page"]["number"] == 1
    assert data["page"]["count"] == 20

    # Get second page
    response = await client.get(
        "/v1/references/search/",
        params={"q": "title:Pagination", "page": 2},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["page"]["number"] == 2
    assert data["page"]["count"] == 5


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        # Syntax error
        ({"q": "(unbalanced parentheses"}, status.HTTP_400_BAD_REQUEST),
        # Invalid sort field (text type)
        ({"q": "foo", "sort": ["title"]}, status.HTTP_400_BAD_REQUEST),
    ],
)
async def test_query_string_error_handling(
    client: AsyncClient,
    search_references: list,  # noqa: ARG001
    params: dict,
    expected_status: int,
) -> None:
    """Test error handling for malformed queries."""
    response = await client.get("/v1/references/search/", params=params)
    assert response.status_code == expected_status


@pytest.fixture
async def cross_field_references(es_client: AsyncElasticsearch):
    """Create references with search terms split across title and abstract fields."""
    references = [
        # "george" in title, "harrison" in abstract
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="George Studies in Modern Science",
                        publication_year=2023,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "This research was conducted by Harrison and colleagues."
                        )
                    )
                ),
            ]
        ),
        # Both terms in title
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="George Harrison Biography",
                        publication_year=2022,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract="A study of musical history and cultural impact."
                    )
                ),
            ]
        ),
        # Only "george" present (should not match AND query)
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="George Washington Papers",
                        publication_year=2021,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract="Historical documents and correspondence."
                    )
                ),
            ]
        ),
    ]

    es_repository = ReferenceESRepository(es_client)
    for reference in references:
        await es_repository.add(reference)
    await es_client.indices.refresh(index="reference")
    return references


async def test_cross_field_and_query(
    client: AsyncClient,
    cross_field_references: list,  # noqa: ARG001
) -> None:
    """
    Test that explicit AND matches terms split across fields.

    Query "george AND harrison" expands to:
        (title:george OR abstract:george) AND (title:harrison OR abstract:harrison)
    """
    response = await client.get(
        "/v1/references/search/",
        params={"q": "george AND harrison"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["total"]["count"] == 2

    titles = {ref["enhancements"][0]["content"]["title"] for ref in data["references"]}
    assert titles == {"George Studies in Modern Science", "George Harrison Biography"}


async def test_same_field_and_query(
    client: AsyncClient,
    cross_field_references: list,  # noqa: ARG001
) -> None:
    """Control test: AND query works when both terms are in the same field."""
    response = await client.get(
        "/v1/references/search/",
        params={"q": "title:(george AND harrison)"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["total"]["count"] == 1
    title = data["references"][0]["enhancements"][0]["content"]["title"]
    assert "George Harrison" in title


@pytest.fixture
async def cross_field_idf_references(es_client: AsyncElasticsearch):
    """
    Create references to test cross_fields scoring behavior.

    Query: "climate change AND health"

    Document A (relevant): "health" in title, "climate change" in abstract
    Document B (irrelevant): all terms in abstract and health in title

    best_fields scores each field separately, so Document B ranks higher
    (all terms in one field).

    cross_fields treats title + abstract as one combined field, so
    Document A ranks higher.

    See: https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-multi-match-query.html#type-cross-fields
    """
    references = [
        # Document A: Relevant - terms split across title and abstract
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Environmental Impacts on Health Review",
                        publication_year=2023,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "This review examines how climate change affects "
                            "human wellbeing outcomes across different regions."
                        )
                    )
                ),
            ]
        ),
        # Document B: Irrelevant - all terms in abstract, health in title
        ReferenceFactory.build(
            enhancements=[
                EnhancementFactory.build(
                    content=BibliographicMetadataEnhancementFactory.build(
                        title="Public Health Report 2022",
                        publication_year=2022,
                    )
                ),
                EnhancementFactory.build(
                    content=AbstractContentEnhancementFactory.build(
                        abstract=(
                            "The change in funding allocation reflects the new "
                            "climate of fiscal responsibility in health systems."
                        )
                    )
                ),
            ]
        ),
        # Additional papers make "health" common in abstracts but rare in titles.
        # This imbalance affects IDF scoring.
        *[
            ReferenceFactory.build(
                enhancements=[
                    EnhancementFactory.build(
                        content=BibliographicMetadataEnhancementFactory.build(
                            title=f"Research Study {i}",
                            publication_year=2020,
                        )
                    ),
                    EnhancementFactory.build(
                        content=AbstractContentEnhancementFactory.build(
                            abstract=(
                                f"We observed change in patient health outcomes {i}."
                            )
                        )
                    ),
                ]
            )
            for i in range(10)
        ],
    ]

    es_repository = ReferenceESRepository(es_client)
    for reference in references:
        await es_repository.add(reference)
    await es_client.indices.refresh(index="reference")
    return references


@pytest.mark.xfail(
    reason=(
        "best_fields prefers documents with all terms in the same field. "
        "Document B (all terms in abstract) ranks higher than Document A "
        "(terms split across title and abstract)."
    )
)
async def test_cross_field_idf_ranking(
    client: AsyncClient,
    cross_field_idf_references: list,  # noqa: ARG001
) -> None:
    """
    Test that the relevant document ranks first.

    Asserts the relevant document (terms split across fields) ranks above
    the irrelevant document (all terms in one field).
    """
    response = await client.get(
        "/v1/references/search/",
        params={"q": "climate change AND health"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["total"]["count"] == 2

    first_result_title = data["references"][0]["enhancements"][0]["content"]["title"]
    assert first_result_title == "Environmental Impacts on Health Review"


async def test_cross_field_idf_ranking_with_cross_fields_type(
    es_client: AsyncElasticsearch,
    cross_field_idf_references: list,  # noqa: ARG001
) -> None:
    """
    Test that cross_fields type ranks split-field matches higher.

    Uses QueryString with type='cross_fields' directly to show that treating
    fields as one combined field improves ranking for the relevant document.
    """
    from elasticsearch.dsl import AsyncSearch
    from elasticsearch.dsl.query import QueryString

    search = AsyncSearch(using=es_client, index="reference").query(
        QueryString(
            query="climate change AND health",
            fields=["title", "abstract"],
            type="cross_fields",
        )
    )

    response = await search.execute()

    # Note: cross_fields returns more results
    # assert response.hits.total.value == 2  # noqa: ERA001

    first_result = response.hits[0].to_dict()
    first_title = first_result["enhancements"][0]["content"]["title"]
    assert first_title == "Environmental Impacts on Health Review"
