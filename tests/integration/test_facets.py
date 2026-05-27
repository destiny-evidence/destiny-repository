"""Integration tests for the `/references/search/facets/` endpoint."""

from collections.abc import AsyncGenerator, Iterator
from uuid import uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from rdflib import Graph

from app.api.exception_handlers import (
    es_exception_handler,
    parse_error_exception_handler,
)
from app.core.exceptions import ESQueryError, ParseError
from app.domain.references import routes as references
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import Visibility
from app.external.vocabulary.client import get_vocabulary_artifact_client

pytestmark = pytest.mark.usefixtures("session")


CONCEPT_A = "https://vocab.example.org/A"
CONCEPT_B = "https://vocab.example.org/B"
CONCEPT_C = "https://vocab.example.org/C"


# ---- Sibling vocabulary fixture for #703 ------------------------------------------

VOCAB_URI = "https://vocab.example.org/test/v1"

# Two schemes: a 2-level hierarchy and a flat one, mirroring the ticket's example.
SIBLING_VOCAB_TURTLE = """\
@prefix ex:   <https://vocab.example.org/test/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Topics  a skos:ConceptScheme .
ex:Biology   a skos:Concept ; skos:inScheme ex:Topics ;
             skos:topConceptOf ex:Topics ; skos:prefLabel "Biology" .
ex:Chemistry a skos:Concept ; skos:inScheme ex:Topics ;
             skos:topConceptOf ex:Topics ; skos:prefLabel "Chemistry" .
ex:Botany       a skos:Concept ; skos:inScheme ex:Topics ;
                skos:broader ex:Biology ; skos:prefLabel "Botany" .
ex:Zoology      a skos:Concept ; skos:inScheme ex:Topics ;
                skos:broader ex:Biology ; skos:prefLabel "Zoology" .
ex:Microbiology a skos:Concept ; skos:inScheme ex:Topics ;
                skos:broader ex:Biology ; skos:prefLabel "Microbiology" .

ex:Region a skos:ConceptScheme .
ex:Africa a skos:Concept ; skos:inScheme ex:Region ;
          skos:topConceptOf ex:Region ; skos:prefLabel "Africa" .
ex:Asia   a skos:Concept ; skos:inScheme ex:Region ;
          skos:topConceptOf ex:Region ; skos:prefLabel "Asia" .
ex:Europe a skos:Concept ; skos:inScheme ex:Region ;
          skos:topConceptOf ex:Region ; skos:prefLabel "Europe" .
"""

BOTANY = "https://vocab.example.org/test/Botany"
ZOOLOGY = "https://vocab.example.org/test/Zoology"
MICROBIOLOGY = "https://vocab.example.org/test/Microbiology"
AFRICA = "https://vocab.example.org/test/Africa"
ASIA = "https://vocab.example.org/test/Asia"
EUROPE = "https://vocab.example.org/test/Europe"
UNKNOWN_URI = "https://vocab.example.org/test/Unknown"


@pytest.fixture
def primed_vocab() -> Iterator[str]:
    """Pre-populate the vocab client's caches with a SKOS sibling fixture."""
    graph = Graph()
    graph.parse(data=SIBLING_VOCAB_TURTLE, format="turtle")
    client = get_vocabulary_artifact_client()
    client._vocabulary_cache[VOCAB_URI] = graph  # noqa: SLF001
    try:
        yield VOCAB_URI
    finally:
        # Each test fixture clears its slot so derived caches re-build.
        client._vocabulary_cache.pop(VOCAB_URI, None)  # noqa: SLF001
        client._concept_labels_cache.pop(VOCAB_URI, None)  # noqa: SLF001
        client._concept_schemes_cache.pop(VOCAB_URI, None)  # noqa: SLF001
        client._concept_siblings_cache.pop(VOCAB_URI, None)  # noqa: SLF001


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


# ---- Sibling-aware facets (#703) -------------------------------------------------


CHEMISTRY = "https://vocab.example.org/test/Chemistry"
_SIBLING_DOC_CONCEPTS = [
    [BOTANY, AFRICA],
    [BOTANY, AFRICA],
    [ZOOLOGY, AFRICA],
    [ZOOLOGY, ASIA],
    [MICROBIOLOGY, EUROPE],
    [CHEMISTRY, AFRICA],
]


@pytest.fixture
async def sibling_references(es_client: AsyncElasticsearch) -> None:
    """Six docs spanning the Biology + Region sibling groups + one Chemistry."""
    for i, concepts in enumerate(_SIBLING_DOC_CONCEPTS, start=1):
        await ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title=f"doc {i}",
            linked_data_concepts=concepts,
        ).save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


def _counts_by_concept(body: dict) -> dict[str, int]:
    return {bucket["concept"]: bucket["count"] for bucket in body["concepts"]}


async def test_sibling_facets_worked_example(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Two-group worked example: each bucket = count if toggled alone."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", f"{BOTANY},{ZOOLOGY}"),
            ("concept", AFRICA),
            ("facet", "concepts"),
            ("vocabulary", primed_vocab),
        ],
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # Topics counts are filtered to docs with Africa; Region counts to docs with
    # (Botany OR Zoology). Microbiology=0 (its only doc is Europe-not-Africa);
    # Europe=0 (its only doc has Microbiology, not Botany/Zoology). Unselected
    # bucket is empty: every concept seen in the post-filtered hits is in a
    # known group.
    counts = _counts_by_concept(response.json())
    assert counts == {
        BOTANY: 2,
        ZOOLOGY: 1,
        MICROBIOLOGY: 0,
        AFRICA: 3,
        ASIA: 1,
        EUROPE: 0,
    }
    assert len(counts) == len(response.json()["concepts"])  # no duplicates


async def test_sibling_facets_unselected_bucket_surfaces_other_concepts(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Concepts outside the filter's sibling sets appear in the unselected agg."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", BOTANY),
            ("facet", "concepts"),
            ("vocabulary", primed_vocab),
        ],
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    # Topics group (filter empty) counts {Botany:2, Zoology:2, Microbiology:1}.
    # Unselected agg restricts to docs with Botany (docs 1, 2), so only Africa
    # (their other concept) surfaces — Chemistry is excluded because its doc
    # has no Botany.
    assert _counts_by_concept(response.json()) == {
        BOTANY: 2,
        ZOOLOGY: 2,
        MICROBIOLOGY: 1,
        AFRICA: 2,
    }


@pytest.mark.parametrize(
    ("concept_params", "vocab", "detail_substring"),
    [
        # Rule (c): URI not in vocabulary.
        ([UNKNOWN_URI], "primed", UNKNOWN_URI),
        # Rule (a): one filter spans sibling sets.
        ([f"{BOTANY},{AFRICA}"], "primed", "different sibling sets"),
        # Rule (b): siblings split across filters.
        ([BOTANY, ZOOLOGY], "primed", "share a sibling set"),
        # vocabulary= missing.
        ([BOTANY], None, "`vocabulary=` is required"),
        # vocabulary= not a URI.
        ([BOTANY], "not a uri", "fully-qualified URI"),
    ],
)
async def test_sibling_facets_rule_violations_return_400(  # noqa: PLR0913
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
    concept_params: list[str],
    vocab: str | None,
    detail_substring: str,
) -> None:
    """Each parametrised case maps to one rule violation -> 400 with detail."""
    params: list[tuple[str, str]] = [("q", "*"), ("facet", "concepts")]
    params.extend(("concept", v) for v in concept_params)
    if vocab is not None:
        params.append(("vocabulary", primed_vocab if vocab == "primed" else vocab))
    response = await client.get("/v1/references/search/facets/", params=params)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert detail_substring in response.json()["detail"]
