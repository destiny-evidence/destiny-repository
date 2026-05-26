"""Unit tests for Elasticsearch repository query string search functionality."""

from uuid import uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl.query import Term, Terms
from elasticsearch.helpers import async_bulk

from app.core.exceptions import ESQueryError
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import Visibility
from app.domain.references.repository import ReferenceESRepository
from app.domain.references.services.world_bank_regions import (
    SOUTH_ASIA,
    SUB_SAHARAN_AFRICA,
)
from app.persistence.es.persistence import FilteredTermsAggSpec
from app.persistence.es.repository import GenericAsyncESRepository
from tests.persistence_models import SimpleDoc, SimpleDomainModel


class SimpleRepository(GenericAsyncESRepository[SimpleDomainModel, SimpleDoc]):
    """Simple repository for testing."""

    def __init__(self, client: AsyncElasticsearch):
        super().__init__(
            client=client,
            domain_cls=SimpleDomainModel,
            persistence_cls=SimpleDoc,
        )


@pytest.fixture
async def simple_repository(
    es_client: AsyncElasticsearch,
) -> SimpleRepository:
    """Create a simple repository with test index."""
    return SimpleRepository(client=es_client)


async def create_simple_doc(
    repository: SimpleRepository,
    title: str,
    year: int,
    content: str,
) -> str:
    """Helper to create and index a simple document."""
    doc = SimpleDomainModel(title=title, year=year, content=content)
    await repository.add(doc)
    return str(doc.id)


@pytest.fixture
async def test_doc(simple_repository: SimpleRepository) -> str:
    """Create a single test document for query string search scenarios."""
    doc_id = await create_simple_doc(
        simple_repository,
        title="test document",
        year=2023,
        content="This is sample content for testing",
    )

    # Refresh index to make document searchable
    await simple_repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )

    return doc_id


@pytest.mark.parametrize(
    ("query", "should_match"),
    [
        # Basic field search
        ("title:test", True),
        ("title:nonexistent", False),
        # Wildcard search
        ("title:test*", True),
        # Boolean operators
        ("title:test AND year:2023", True),
        ("title:test OR title:nonexistent", True),
        ("title:test NOT content:missing", True),
        # Field existence
        ("_exists_:title", True),
        ("_exists_:nonexistent_field", False),
        # Multi-field search
        ("test", True),
        # Phrase search
        ('"test document"', True),
        # Range query
        ("year:[2020 TO 2024]", True),
        # Phrase with slop
        ('"test document"~0', True),
        ('"document test"~2', True),
        ('"test missing"~1', False),
        # Fuzzy search
        ("title:tset~1", True),
        ("title:unrelated~1", False),
        ("content:sampel~1", True),
        # Complex query
        (
            "year:[2020 TO 2025] "
            'AND "test document" '
            "AND title:tset~1 "
            "AND NOT nonexistent_field:foobar",
            True,
        ),
        (
            "year:[2020 TO 2025] "
            'AND "test document" '
            "AND title:tset "  # No fuzzy, exact match required
            "AND NOT nonexistent_field:foobar",
            False,
        ),
    ],
)
async def test_query_string_search_scenarios(
    simple_repository: SimpleRepository,
    test_doc: str,
    query: str,
    *,
    should_match: bool,
):
    """Test various Lucene query syntax scenarios."""
    results = await simple_repository.search_with_query_string(query)

    if should_match:
        assert len(results.hits) == 1
        assert results.total.value == 1
        assert str(results.hits[0].id) == test_doc
    else:
        assert len(results.hits) == 0
        assert results.total.value == 0
    assert results.total.relation == "eq"


@pytest.mark.parametrize(
    "query",
    [
        '"unclosed phrase',  # Unbalanced quote
        "(unclosed parenthesis",  # Unbalanced parenthesis
        "title:foo AND OR bar",  # Invalid boolean logic
        "title:foo:bar",  # Unescaped colon
        "year:[2020 TO ]",  # Invalid range
        "title:foo^",  # Invalid boost
    ],
)
async def test_query_string_search_invalid_syntax(
    simple_repository: SimpleRepository,
    query: str,
):
    """Test that invalid Lucene query syntax raises an error."""
    with pytest.raises(ESQueryError):
        await simple_repository.search_with_query_string(query)


async def test_query_string_search_many_results(
    simple_repository: SimpleRepository,
):
    """Test searching with many results returns proper total count."""
    # Use bulk API for better performance

    docs = [
        SimpleDoc(
            title="common title",
            year=2023,
            content=f"content {i}",
            meta={"id": uuid7()},
        )
        for i in range(10001)
    ]

    # Prepare actions for bulk
    actions = [doc.to_dict(include_meta=True) for doc in docs]
    await async_bulk(simple_repository._client, actions, index=SimpleDoc.Index.name)  # noqa: SLF001

    await simple_repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )

    results = await simple_repository.search_with_query_string("title:common")

    assert len(results.hits) == 20
    assert results.total.value == 10000
    assert results.total.relation == "gte"


async def test_query_string_search_with_fields(
    simple_repository: SimpleRepository,
):
    """Test searching with specific fields restricts search scope."""
    doc_id = await create_simple_doc(
        simple_repository,
        title="searchterm in title",
        year=2023,
        content="other content here",
    )

    await simple_repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )

    # Search with both title and content - should find it
    results = await simple_repository.search_with_query_string(
        "searchterm AND other",
        fields=["title", "content"],
    )
    assert len(results.hits) == 1
    assert str(results.hits[0].id) == doc_id

    # Search restricted to year field only - should first error
    # because it's not allowed to search text in a numeric field,
    # then should find nothing
    with pytest.raises(ESQueryError):
        results_year_only = await simple_repository.search_with_query_string(
            "searchterm",
            fields=["year"],
        )

    results_year_only = await simple_repository.search_with_query_string(
        "2000",
        fields=["year"],
    )
    assert len(results_year_only.hits) == 0


async def test_query_string_search_pagination(
    simple_repository: SimpleRepository,
):
    """Test pagination in query string search."""
    docs = [
        SimpleDoc(
            title="pagination",
            year=2023,
            content="content",
            meta={"id": uuid7()},
        )
        for _ in range(55)
    ]
    doc_ids = {doc.meta.id for doc in docs}

    await async_bulk(
        simple_repository._client,  # noqa: SLF001
        [doc.to_dict(include_meta=True) for doc in docs],
        index=SimpleDoc.Index.name,
    )
    await simple_repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )

    # Test page 1
    results_page_1 = await simple_repository.search_with_query_string(
        "title:pagination",
        page=1,
        page_size=20,
    )
    assert len(results_page_1.hits) == 20
    assert results_page_1.page == 1
    assert results_page_1.total.value == 55
    assert results_page_1.total.relation == "eq"

    # Test page 2
    results_page_2 = await simple_repository.search_with_query_string(
        "title:pagination",
        page=2,
        page_size=20,
    )
    assert len(results_page_2.hits) == 20
    assert results_page_2.page == 2

    # Test page 3 (partial)
    results_page_3 = await simple_repository.search_with_query_string(
        "title:pagination",
        page=3,
        page_size=20,
    )
    assert len(results_page_3.hits) == 15
    assert results_page_3.page == 3

    # Verify all documents are accounted for
    all_returned_ids = {
        hit.id
        for hit in results_page_1.hits + results_page_2.hits + results_page_3.hits
    }
    assert all_returned_ids == doc_ids

    # Test page 4 (empty)
    results_page_4 = await simple_repository.search_with_query_string(
        "title:pagination",
        page=4,
        page_size=20,
    )
    assert len(results_page_4.hits) == 0


async def test_query_string_search_sorting(
    simple_repository: SimpleRepository,
):
    """Test sorting search results by different fields and directions."""
    # Create documents with different years
    doc_2020 = await create_simple_doc(
        simple_repository, title="doc", year=2020, content="content"
    )
    doc_2021 = await create_simple_doc(
        simple_repository, title="doc", year=2021, content="content"
    )
    doc_2022 = await create_simple_doc(
        simple_repository, title="doc", year=2022, content="content"
    )

    await simple_repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )

    # Test sorting by year ascending
    results_asc = await simple_repository.search_with_query_string(
        "_exists_:year",
        sort=["year"],
    )
    assert len(results_asc.hits) == 3
    assert str(results_asc.hits[0].id) == doc_2020
    assert str(results_asc.hits[1].id) == doc_2021
    assert str(results_asc.hits[2].id) == doc_2022

    # Test sorting by year descending
    results_desc = await simple_repository.search_with_query_string(
        "_exists_:year",
        sort=["-year"],
    )
    assert len(results_desc.hits) == 3
    assert str(results_desc.hits[0].id) == doc_2022
    assert str(results_desc.hits[1].id) == doc_2021
    assert str(results_desc.hits[2].id) == doc_2020


async def test_query_string_search_with_document(
    simple_repository: SimpleRepository,
    test_doc: str,
):
    """Test that parse_document=True returns the full document."""
    results = await simple_repository.search_with_query_string(
        "title:test",
        parse_document=True,
    )

    assert len(results.hits) == 1
    assert str(results.hits[0].id) == test_doc
    assert results.hits[0].document is not None
    assert isinstance(results.hits[0].document, SimpleDomainModel)
    assert results.hits[0].document.title == "test document"
    assert results.hits[0].document.year == 2023
    assert results.hits[0].document.content == "This is sample content for testing"


@pytest.fixture
async def reference_repository(
    es_client: AsyncElasticsearch,
) -> ReferenceESRepository:
    """Create a reference repository with test index."""
    return ReferenceESRepository(client=es_client)


@pytest.fixture
async def linked_data_ref(
    es_client: AsyncElasticsearch,
) -> str:
    """Index a reference with linked data fields populated."""
    ref_id = uuid7()
    doc = ReferenceDocument(
        meta={"id": ref_id},
        visibility=Visibility.PUBLIC,
        title="Effectiveness of reading interventions",
        linked_data_concepts=[
            "https://vocab.esea.education/C00008",
            "https://vocab.esea.education/C00002",
        ],
        linked_data_labels=["Journal Article", "Primary Education"],
        linked_data_evaluated_properties=[
            "https://vocab.esea.education/documentType",
            "https://vocab.esea.education/educationLevel",
        ],
        linked_data_countries=["KE", "GH"],
        linked_data_country_wb_regions=[SUB_SAHARAN_AFRICA],
    )
    await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)
    return str(ref_id)


ESEA_CONCEPT = "https://vocab.esea.education/C00008"
ESEA_PROP = "https://vocab.esea.education/documentType"


@pytest.mark.parametrize(
    ("query", "should_match"),
    [
        # Exact concept URI match (Keyword field, quoted to avoid colon parsing)
        (f'linked_data_concepts:"{ESEA_CONCEPT}"', True),
        ('linked_data_concepts:"https://vocab.esea.education/C99999"', False),
        # Full-text label search (Text field)
        ("linked_data_labels:Journal", True),
        ("linked_data_labels:Primary", True),
        ("linked_data_labels:Nonexistent", False),
        # Exact property URI match (Keyword field, quoted)
        (f'linked_data_evaluated_properties:"{ESEA_PROP}"', True),
        (
            "linked_data_evaluated_properties:"
            '"https://vocab.esea.education/nonexistent"',
            False,
        ),
        # Field existence
        ("_exists_:linked_data_concepts", True),
        # Country code match (Keyword field)
        ("linked_data_countries:KE", True),
        ("linked_data_countries:GH", True),
        ("linked_data_countries:ZZ", False),
        # World Bank region ID match (Keyword field)
        (f"linked_data_country_wb_regions:{SUB_SAHARAN_AFRICA}", True),
        (f"linked_data_country_wb_regions:{SOUTH_ASIA}", False),
    ],
)
async def test_linked_data_field_search(
    reference_repository: ReferenceESRepository,
    linked_data_ref: str,
    query: str,
    *,
    should_match: bool,
):
    """Test that linked data fields are queryable via Lucene query string."""
    results = await reference_repository.search_with_query_string(query)

    if should_match:
        assert len(results.hits) == 1
        assert str(results.hits[0].id) == linked_data_ref
    else:
        assert len(results.hits) == 0


CONCEPT_A = "https://vocab.example.org/A"
CONCEPT_B = "https://vocab.example.org/B"
CONCEPT_C = "https://vocab.example.org/C"
CONCEPT_D = "https://vocab.example.org/D"


@pytest.fixture
async def filtered_agg_refs(es_client: AsyncElasticsearch) -> None:
    """Reference docs covering the filtered-agg scenarios."""
    docs = [
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="alpha",
            linked_data_concepts=[CONCEPT_A, CONCEPT_B],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="alpha",
            linked_data_concepts=[CONCEPT_A, CONCEPT_C],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="beta",
            linked_data_concepts=[CONCEPT_B],
        ),
        ReferenceDocument(
            meta={"id": uuid7()},
            visibility=Visibility.PUBLIC,
            title="beta",
            linked_data_concepts=[CONCEPT_D],
        ),
    ]
    for doc in docs:
        await doc.save(using=es_client)
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)


def _counts(buckets: list) -> dict[str, int]:
    return {bucket.key: bucket.count for bucket in buckets}


UNFILTERED_COUNTS = {CONCEPT_A: 2, CONCEPT_B: 2, CONCEPT_C: 1, CONCEPT_D: 1}


async def test_filtered_terms_aggregation_per_agg_filter_and_unfiltered(
    reference_repository: ReferenceESRepository,
    filtered_agg_refs: None,  # noqa: ARG001
) -> None:
    """Per-spec filter_clauses scope that agg only; empty filter counts all matches."""
    result = await reference_repository.execute_filtered_terms_aggregations(
        "*",
        aggs=[
            FilteredTermsAggSpec(
                name="with_a",
                field="linked_data_concepts",
                filter_clauses=(Terms(linked_data_concepts=[CONCEPT_A]),),
                size=10,
            ),
            FilteredTermsAggSpec(name="all", field="linked_data_concepts", size=10),
        ],
    )

    assert _counts(result["with_a"]) == {CONCEPT_A: 2, CONCEPT_B: 1, CONCEPT_C: 1}
    assert _counts(result["all"]) == UNFILTERED_COUNTS


async def test_filtered_terms_aggregation_include_exclude_and_min_doc_count(
    reference_repository: ReferenceESRepository,
    filtered_agg_refs: None,  # noqa: ARG001
) -> None:
    """``include`` with ``min_doc_count=0`` surfaces zero buckets; ``exclude`` drops."""
    # `title:beta` matches only docs tagged B and D. A and C are indexed in the
    # other (`alpha`) docs but absent here — `min_doc_count=0` + `include` should
    # still emit A=0 and C=0. `exclude` over the same docs drops B.
    result = await reference_repository.execute_filtered_terms_aggregations(
        "title:beta",
        aggs=[
            FilteredTermsAggSpec(
                name="included",
                field="linked_data_concepts",
                include=(CONCEPT_A, CONCEPT_B, CONCEPT_C),
                min_doc_count=0,
                size=10,
            ),
            FilteredTermsAggSpec(
                name="excluded",
                field="linked_data_concepts",
                exclude=(CONCEPT_B,),
                size=10,
            ),
        ],
    )

    assert _counts(result["included"]) == {CONCEPT_A: 0, CONCEPT_B: 1, CONCEPT_C: 0}
    assert _counts(result["excluded"]) == {CONCEPT_D: 1}


async def test_filtered_terms_aggregation_base_and_post_filter(
    reference_repository: ReferenceESRepository,
    filtered_agg_refs: None,  # noqa: ARG001
) -> None:
    """``base_filter_clauses`` apply to aggs; ``post_filter_clauses`` don't."""
    # base_filter narrows the agg to "alpha" docs only ({A,B} and {A,C}).
    # post_filter would narrow hits to docs tagged D, but the agg should ignore it.
    result = await reference_repository.execute_filtered_terms_aggregations(
        "*",
        base_filter_clauses=(Term(title="alpha"),),
        post_filter_clauses=(Terms(linked_data_concepts=[CONCEPT_D]),),
        aggs=[
            FilteredTermsAggSpec(name="cs", field="linked_data_concepts", size=10),
        ],
    )

    assert _counts(result["cs"]) == {CONCEPT_A: 2, CONCEPT_B: 1, CONCEPT_C: 1}
