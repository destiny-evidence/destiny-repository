"""Integration tests for the `/references/search/cross-facets/` endpoint."""

from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from rdflib import Graph

from app.api.exception_handlers import (
    es_exception_handler,
    parse_error_exception_handler,
    vocabulary_fetch_exception_handler,
)
from app.core.exceptions import ESQueryError, ParseError, VocabularyFetchError
from app.domain.references import routes as references
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import Visibility
from app.external.vocabulary.client import get_vocabulary_artifact_client

pytestmark = pytest.mark.usefixtures("session")


# ---- Vocabulary fixture: two schemes (Topics, Region) ----------------------------

VOCAB_URI = "https://vocab.evidence-repository.org/test/v1"
TOPICS_SCHEME = "https://vocab.example.org/test/Topics"
REGION_SCHEME = "https://vocab.example.org/test/Region"

VOCAB_TURTLE = """\
@prefix ex:   <https://vocab.example.org/test/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Topics a skos:ConceptScheme .
ex:Botany       a skos:Concept ; skos:inScheme ex:Topics ; skos:prefLabel "Botany" .
ex:Zoology      a skos:Concept ; skos:inScheme ex:Topics ; skos:prefLabel "Zoology" .
ex:Microbiology a skos:Concept ; skos:inScheme ex:Topics ;
                skos:prefLabel "Microbiology" .

ex:Region a skos:ConceptScheme .
ex:Africa a skos:Concept ; skos:inScheme ex:Region ; skos:prefLabel "Africa" .
ex:Asia   a skos:Concept ; skos:inScheme ex:Region ; skos:prefLabel "Asia" .
ex:Europe a skos:Concept ; skos:inScheme ex:Region ; skos:prefLabel "Europe" .
"""

BOTANY = "https://vocab.example.org/test/Botany"
ZOOLOGY = "https://vocab.example.org/test/Zoology"
MICROBIOLOGY = "https://vocab.example.org/test/Microbiology"
AFRICA = "https://vocab.example.org/test/Africa"
ASIA = "https://vocab.example.org/test/Asia"
EUROPE = "https://vocab.example.org/test/Europe"

# ISO 3166-1 alpha-2 codes and their World Bank region IDs (KE/UG -> SSF, US -> NAC).
COUNTRY_KE = "KE"
COUNTRY_UG = "UG"
COUNTRY_US = "US"
REGION_SSF = "SSF"
REGION_NAC = "NAC"

NOT_A_SCHEME = "https://vocab.example.org/test/NotAScheme"
BAD_HOST_VOCAB = "https://vocab.evil.example.org/v.ttl"


@pytest.fixture
def primed_vocab() -> Iterator[str]:
    """Pre-populate the vocab client's graph cache with the two-scheme fixture."""
    graph = Graph()
    graph.parse(data=VOCAB_TURTLE, format="turtle")
    client = get_vocabulary_artifact_client()
    client._vocabulary_cache[VOCAB_URI] = graph  # noqa: SLF001
    try:
        yield VOCAB_URI
    finally:
        client._vocabulary_cache.pop(VOCAB_URI, None)  # noqa: SLF001
        client.get_scheme_members.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application instance for testing."""
    app = FastAPI(
        exception_handlers={
            ESQueryError: es_exception_handler,
            ParseError: parse_error_exception_handler,
            VocabularyFetchError: vocabulary_fetch_exception_handler,
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
async def cross_references(es_client: AsyncElasticsearch) -> None:
    """
    Index references with Topics/Region concepts plus countries and wb regions.

    - doc 1: Botany, Africa;          KE; SSF
    - doc 2: Botany, Africa;          KE; SSF
    - doc 3: Zoology, Asia;           US; NAC
    - doc 4: Microbiology, Europe;    UG; SSF
    - doc 5: Botany, Zoology, Africa; KE; SSF   (multi-valued on Topics)
    - doc 6: Botany, Zoology, Africa; KE; SSF   (multi-valued on Topics)
    """
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Botany in Africa one",
            linked_data_concepts=[BOTANY, AFRICA],
            linked_data_countries=[COUNTRY_KE],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Botany in Africa two",
            linked_data_concepts=[BOTANY, AFRICA],
            linked_data_countries=[COUNTRY_KE],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Zoology in Asia",
            linked_data_concepts=[ZOOLOGY, ASIA],
            linked_data_countries=[COUNTRY_US],
            linked_data_country_wb_regions=[REGION_NAC],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Microbiology in Europe",
            linked_data_concepts=[MICROBIOLOGY, EUROPE],
            linked_data_countries=[COUNTRY_UG],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Botany and Zoology in Africa",
            linked_data_concepts=[BOTANY, ZOOLOGY, AFRICA],
            linked_data_countries=[COUNTRY_KE],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="More botany and zoology in Africa",
            linked_data_concepts=[BOTANY, ZOOLOGY, AFRICA],
            linked_data_countries=[COUNTRY_KE],
            linked_data_country_wb_regions=[REGION_SSF],
        ),
    ]
    for doc in docs:
        await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


@pytest.fixture
async def partly_tagged_references(es_client: AsyncElasticsearch) -> None:
    """
    Index references carrying a value on only some of the facet fields.

    - doc 1: Botany;  KE
    - doc 2: Botany;  -
    - doc 3: -;       KE
    - doc 4: Zoology; KE
    """
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Tagged both ways",
            linked_data_concepts=[BOTANY],
            linked_data_countries=[COUNTRY_KE],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Concepts only",
            linked_data_concepts=[BOTANY],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Countries only",
            linked_data_countries=[COUNTRY_KE],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            id=uuid7(),
            visibility=Visibility.PUBLIC,
            title="Tagged both ways too",
            linked_data_concepts=[ZOOLOGY],
            linked_data_countries=[COUNTRY_KE],
        ),
    ]
    for doc in docs:
        await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


def _cells(body: dict) -> set[tuple[str, str, int]]:
    return {(c["axes"][0], c["axes"][1], c["count"]) for c in body["cells"]}


def _totals(body: dict) -> tuple[int, int]:
    return body["totals"]["search"]["count"], body["totals"]["mapped"]["count"]


async def test_scheme_by_scheme_cross_tab(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Cells are sorted by descending count, interleaving axis values."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [TOPICS_SCHEME, REGION_SCHEME],
            "vocabulary": primed_vocab,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    assert _totals(body) == (6, 6)
    assert body["total"] == body["totals"]["mapped"]
    assert body["cells"] == [
        {"axes": [BOTANY, AFRICA], "count": 4},
        {"axes": [ZOOLOGY, AFRICA], "count": 2},
        {"axes": [MICROBIOLOGY, EUROPE], "count": 1},
        {"axes": [ZOOLOGY, ASIA], "count": 1},
    ]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        # concept axis x region-literal axis (include omitted on the literal axis)
        (
            {"axes": [TOPICS_SCHEME, "country_wb_regions"], "vocabulary": VOCAB_URI},
            {
                (BOTANY, REGION_SSF, 4),
                (ZOOLOGY, REGION_NAC, 1),
                (ZOOLOGY, REGION_SSF, 2),
                (MICROBIOLOGY, REGION_SSF, 1),
            },
        ),
        # two literal axes, no vocabulary needed
        (
            {"axes": ["countries", "country_wb_regions"]},
            {
                (COUNTRY_KE, REGION_SSF, 4),
                (COUNTRY_US, REGION_NAC, 1),
                (COUNTRY_UG, REGION_SSF, 1),
            },
        ),
        # identical axes -> diagonal co-occurrence matrix
        (
            {"axes": ["country_wb_regions", "country_wb_regions"]},
            {(REGION_SSF, REGION_SSF, 5), (REGION_NAC, REGION_NAC, 1)},
        ),
    ],
)
async def test_cross_facet_cells(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
    primed_vocab: str,  # noqa: ARG001
    params: dict,
    expected: set,
) -> None:
    """Mixed, literal-only, and identical axes each return the expected cells."""
    response = await client.get(
        "/v1/references/search/cross-facets/", params={"q": "*", **params}
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert _cells(response.json()) == expected


async def test_query_string_and_empty_result(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
) -> None:
    """`q` narrows the matrix; a query matching nothing yields an empty matrix."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={"q": "title:Asia", "axes": ["countries", "country_wb_regions"]},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert _totals(response.json()) == (1, 1)
    assert _cells(response.json()) == {(COUNTRY_US, REGION_NAC, 1)}

    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={"q": "title:nope_xyz", "axes": ["countries", "country_wb_regions"]},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert _totals(response.json()) == (0, 0)
    assert response.json()["cells"] == []


async def test_panel_filter_narrows_whole_matrix(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
) -> None:
    """A panel filter narrows every cell, even where it overlaps an axis."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": ["countries", "country_wb_regions"],
            "country": COUNTRY_KE,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # Only KE docs (1, 2, 5, 6) survive, all SSF — the country filter overlaps the
    # country axis and still applies, leaving KE as the only row.
    assert _totals(response.json()) == (4, 4)
    assert _cells(response.json()) == {(COUNTRY_KE, REGION_SSF, 4)}


async def test_multiple_andd_filters_narrow(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
) -> None:
    """Multiple filters AND (no OR-grouping): KE and US together match nothing."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": ["countries", "country_wb_regions"],
            "country": [COUNTRY_KE, COUNTRY_US],
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert _totals(response.json()) == (0, 0)
    assert response.json()["cells"] == []


async def test_filter_overlapping_a_scheme_axis_still_applies(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """A concept filter on the row scheme narrows docs but doesn't restrict the axis."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [TOPICS_SCHEME, "country_wb_regions"],
            "concept": BOTANY,
            "vocabulary": primed_vocab,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # Restricted to Botany docs (1, 2, 5, 6); Zoology still surfaces because docs 5/6
    # carry it too — the overlapping filter narrows the matrix, not the axis.
    assert _totals(response.json()) == (4, 4)
    assert _cells(response.json()) == {
        (BOTANY, REGION_SSF, 4),
        (ZOOLOGY, REGION_SSF, 2),
    }


async def test_mapped_total_excludes_references_off_the_matrix(
    client: AsyncClient,
    partly_tagged_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """`mapped` counts only references with an in-scope value on both axes."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [TOPICS_SCHEME, "countries"],
            "vocabulary": primed_vocab,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # Docs 2 and 3 each lack an axis, so they match the search but not the matrix.
    assert _totals(response.json()) == (4, 2)
    assert _cells(response.json()) == {
        (BOTANY, COUNTRY_KE, 1),
        (ZOOLOGY, COUNTRY_KE, 1),
    }


async def test_mapped_total_excludes_concepts_outside_the_scheme(
    client: AsyncClient,
    partly_tagged_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """A value outside a scheme axis's members isn't presence on that axis."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [REGION_SCHEME, "countries"],
            "vocabulary": primed_vocab,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # No doc carries a Region concept, so nothing is mapped despite 4 search matches.
    assert _totals(response.json()) == (4, 0)
    assert response.json()["cells"] == []


async def test_mapped_total_dedupes_multi_valued_references(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """A reference spanning several cells is counted once in `mapped`."""
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [TOPICS_SCHEME, REGION_SCHEME],
            "vocabulary": primed_vocab,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    # Docs 5 and 6 carry two Topics each, so cells over-count them; `mapped` doesn't.
    assert sum(c["count"] for c in body["cells"]) == 8
    assert _totals(body) == (6, 6)


@pytest.mark.parametrize(
    ("params", "expected_status", "detail"),
    [
        # scheme axis with no vocabulary
        ({"axes": [TOPICS_SCHEME, "countries"]}, 400, "vocabulary"),
        # matrix too large (256 x 256 countries)
        ({"axes": ["countries", "countries"]}, 400, "exceeding the limit"),
        # scheme URI absent from the vocabulary
        (
            {"axes": [NOT_A_SCHEME, "countries"], "vocabulary": VOCAB_URI},
            400,
            "no members",
        ),
        # vocabulary host outside the allowed domain
        (
            {"axes": [TOPICS_SCHEME, "countries"], "vocabulary": BAD_HOST_VOCAB},
            422,
            None,
        ),
        # not exactly two axes (tuple length enforced by the schema)
        ({"axes": ["countries"]}, 422, None),
        ({"axes": ["countries", "countries", "countries"]}, 422, None),
    ],
)
async def test_cross_facet_request_rejected(
    client: AsyncClient,
    primed_vocab: str,  # noqa: ARG001
    params: dict,
    expected_status: int,
    detail: str | None,
) -> None:
    """
    Bad axes, oversized matrices, and bad vocabularies are rejected (4xx).

    These all fail validation before any ES query, so no indexed docs are needed.
    """
    response = await client.get(
        "/v1/references/search/cross-facets/", params={"q": "*", **params}
    )
    assert response.status_code == expected_status, response.text
    if detail:
        assert detail in response.text


async def test_unfetchable_vocabulary_returns_502(
    client: AsyncClient,
    cross_references: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unfetchable (but host-valid) vocabulary is an upstream failure: 502."""
    monkeypatch.setattr(
        get_vocabulary_artifact_client(),
        "get_scheme_members",
        AsyncMock(side_effect=VocabularyFetchError("bad", "boom")),
    )
    response = await client.get(
        "/v1/references/search/cross-facets/",
        params={
            "q": "*",
            "axes": [TOPICS_SCHEME, "countries"],
            "vocabulary": "https://vocab.evidence-repository.org/test/missing",
        },
    )
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
