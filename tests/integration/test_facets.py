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
from app.external.vocabulary.client import (
    _normalise_top_concept_triples,
    get_vocabulary_artifact_client,
)

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
    _normalise_top_concept_triples(graph)
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


@pytest.fixture
async def sibling_references(es_client: AsyncElasticsearch) -> None:
    """
    Index references covering the ticket's worked example.

    Layout (every doc has at least one Topics concept and one Region concept,
    so concept-filter intersections are well-defined):

    - doc 1: [Botany, Africa]
    - doc 2: [Botany, Africa]
    - doc 3: [Zoology, Africa]
    - doc 4: [Zoology, Asia]
    - doc 5: [Microbiology, Europe]
    - doc 6: [Chemistry, Africa]  (an "unselected" concept outside the Biology
                                   sibling set)
    """
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 1",
            linked_data_concepts=[BOTANY, AFRICA],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 2",
            linked_data_concepts=[BOTANY, AFRICA],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 3",
            linked_data_concepts=[ZOOLOGY, AFRICA],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 4",
            linked_data_concepts=[ZOOLOGY, ASIA],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 5",
            linked_data_concepts=[MICROBIOLOGY, EUROPE],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="doc 6",
            linked_data_concepts=["https://vocab.example.org/test/Chemistry", AFRICA],
        ),
    ]
    for doc in docs:
        await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


def _counts_by_concept(body: dict) -> dict[str, int]:
    return {bucket["concept"]: bucket["count"] for bucket in body["concepts"]}


async def test_sibling_facets_no_concept_filter_is_naive_path(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,  # noqa: ARG001 — present but unused without a concept filter
) -> None:
    """Without a `concept=` filter, today's naive aggregation is returned."""
    response = await client.get(
        "/v1/references/search/facets/",
        params={"q": "*", "facet": "concepts"},
    )
    assert response.status_code == status.HTTP_200_OK
    counts = _counts_by_concept(response.json())
    assert counts == {
        BOTANY: 2,
        ZOOLOGY: 2,
        MICROBIOLOGY: 1,
        AFRICA: 4,
        ASIA: 1,
        EUROPE: 1,
        "https://vocab.example.org/test/Chemistry": 1,
    }


async def test_sibling_facets_worked_example(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Per the ticket: each bucket is "count if this concept were toggled alone"."""
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
    counts = _counts_by_concept(response.json())
    # Topics group: filter applies AFRICA. Documents with Africa AND each
    # topic concept:
    #   Botany       -> docs 1, 2  -> 2
    #   Zoology      -> doc 3       -> 1
    #   Microbiology -> doc 5 has Microbiology AND Europe (not Africa) -> 0
    # Region group: filter applies (Botany OR Zoology). Documents matching
    # (Botany OR Zoology) AND each region:
    #   Africa -> docs 1, 2, 3 -> 3
    #   Asia   -> doc 4         -> 1
    #   Europe -> 0 (doc 5 has Microbiology not Botany/Zoology)
    # unselected: filter applies (Botany OR Zoology) AND Africa.
    #   That's docs 1, 2, 3. linked_data_concepts in those docs are
    #   {Botany, Zoology, Africa} — all already covered, so the unselected
    #   bucket is empty.
    assert counts == {
        BOTANY: 2,
        ZOOLOGY: 1,
        MICROBIOLOGY: 0,
        AFRICA: 3,
        ASIA: 1,
        EUROPE: 0,
    }
    # Bucket uniqueness: no URI appears twice.
    concept_uris = [bucket["concept"] for bucket in response.json()["concepts"]]
    assert len(concept_uris) == len(set(concept_uris))


async def test_sibling_facets_unselected_bucket_surfaces_unknown_concepts(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """A concept outside the filters' sibling sets appears in the unselected agg."""
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
    counts = _counts_by_concept(response.json())
    # Topics group: include = {Botany, Zoology, Microbiology}; filter is empty
    # (no other groups). Counts across the whole index:
    #   Botany=2, Zoology=2, Microbiology=1.
    # Unselected: filter is "must contain Botany" -> docs 1, 2. Their
    # non-group concepts are {Africa} -> Africa=2. (Chemistry would be in
    # docs without Botany, so it's filtered out.)
    assert counts == {
        BOTANY: 2,
        ZOOLOGY: 2,
        MICROBIOLOGY: 1,
        AFRICA: 2,
    }


async def test_sibling_facets_unknown_concept_returns_400(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Rule (c): a concept URI not in the supplied vocab is rejected."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", UNKNOWN_URI),
            ("facet", "concepts"),
            ("vocabulary", primed_vocab),
        ],
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert UNKNOWN_URI in response.json()["detail"]


async def test_sibling_facets_cross_sibling_set_in_one_filter_returns_400(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Rule (a): a single `?concept=` must not span sibling sets."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", f"{BOTANY},{AFRICA}"),
            ("facet", "concepts"),
            ("vocabulary", primed_vocab),
        ],
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "different sibling sets" in response.json()["detail"]


async def test_sibling_facets_siblings_split_across_filters_returns_400(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
    primed_vocab: str,
) -> None:
    """Rule (b): two filters' sibling sets must be disjoint."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", BOTANY),
            ("concept", ZOOLOGY),
            ("facet", "concepts"),
            ("vocabulary", primed_vocab),
        ],
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "share a sibling set" in response.json()["detail"]


async def test_sibling_facets_missing_vocab_with_concept_filter_returns_400(
    client: AsyncClient,
    sibling_references: None,  # noqa: ARG001
) -> None:
    """`vocabulary=` is required when filtering on concepts + requesting concepts."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", BOTANY),
            ("facet", "concepts"),
        ],
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "`vocabulary=` is required" in response.json()["detail"]


async def test_sibling_facets_invalid_vocab_uri_returns_400(
    client: AsyncClient,
) -> None:
    """The vocab parser rejects non-URI strings."""
    response = await client.get(
        "/v1/references/search/facets/",
        params=[
            ("q", "*"),
            ("concept", BOTANY),
            ("facet", "concepts"),
            ("vocabulary", "not a uri"),
        ],
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "fully-qualified URI" in response.json()["detail"]
