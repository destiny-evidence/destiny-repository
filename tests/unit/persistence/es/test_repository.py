"""Unit tests for Elasticsearch repository query string search functionality."""

from typing import Any
from uuid import uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl import Text, mapped_field
from elasticsearch.dsl.query import Term
from elasticsearch.helpers import async_bulk

from app.core.exceptions import ESError, ESQueryError
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import SearchQuery, Visibility
from app.domain.references.repository import ReferenceESRepository
from app.domain.references.services.world_bank_regions import (
    SOUTH_ASIA,
    SUB_SAHARAN_AFRICA,
)
from app.persistence.es.persistence import GenericESPersistence
from app.persistence.es.repository import ES_MAX_PAGE_SIZE, GenericAsyncESRepository
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


def build_simple_docs(count: int, *, title: str, year: int = 2000) -> list[SimpleDoc]:
    """Build ``count`` indexable SimpleDocs sharing a title (and year)."""
    docs = []
    for _ in range(count):
        doc_id = uuid7()
        docs.append(
            SimpleDoc(
                meta={"id": doc_id},
                id=doc_id,
                title=title,
                year=year,
                content="content",
            )
        )
    return docs


async def bulk_index(repository: SimpleRepository, docs: list[SimpleDoc]) -> None:
    """Bulk-index docs and refresh so they are immediately searchable."""
    await async_bulk(
        repository._client,  # noqa: SLF001
        [doc.to_dict(include_meta=True) for doc in docs],
        index=SimpleDoc.Index.name,
    )
    await repository._client.indices.refresh(  # noqa: SLF001
        index=SimpleDoc.Index.name
    )


def test_scan_sort_keys_prefers_mapped_id(simple_repository: SimpleRepository):
    """When the index maps ``id``, it is appended as the tiebreaker."""
    assert simple_repository._scan_sort_keys(["_score"]) == [  # noqa: SLF001
        "_score",
        {"id": {"order": "desc"}},
    ]


def test_scan_sort_keys_does_not_duplicate_id(simple_repository: SimpleRepository):
    """A caller already sorting on ``id`` is not given a second id key."""
    assert simple_repository._scan_sort_keys([{"id": {"order": "asc"}}]) == [  # noqa: SLF001
        {"id": {"order": "asc"}}
    ]


def test_scan_sort_keys_falls_back_to_shard_doc(es_client: AsyncElasticsearch):
    """Without a mapped ``id``, ``_shard_doc`` is used as the tiebreaker."""

    class NoIdDoc(GenericESPersistence):
        title: str = mapped_field(Text())

        class Index:
            name = "test_no_id"

        def to_domain(self) -> SimpleDomainModel:
            return SimpleDomainModel(title=self.title)

        @classmethod
        def from_domain(cls, domain_model: SimpleDomainModel) -> "NoIdDoc":
            return cls(title=domain_model.title)

    repository = GenericAsyncESRepository(es_client, SimpleDomainModel, NoIdDoc)
    assert repository._scan_sort_keys(["_score"]) == ["_score", "_shard_doc"]  # noqa: SLF001


async def test_scan_paginates_all_results(simple_repository: SimpleRepository):
    """Scan yields every match exactly once across incrementing pages."""
    docs = build_simple_docs(55, title="scan")
    await bulk_index(simple_repository, docs)

    pages = [
        page
        async for page in simple_repository.scan_with_query_string(
            "title:scan", page_size=20
        )
    ]

    assert [page.page for page in pages] == [1, 2, 3]
    # Total is exact (track_total_hits) and identical on every page.
    assert all(page.total.value == 55 for page in pages)
    assert all(page.total.relation == "eq" for page in pages)

    returned = [hit.id for page in pages for hit in page.hits]
    assert len(returned) == 55
    assert {str(rid) for rid in returned} == {str(doc.id) for doc in docs}


async def test_scan_tiebreaker_orders_fully_tied_sort(
    simple_repository: SimpleRepository,
):
    """A sort whose values are all equal still pages without skips or dupes."""
    docs = build_simple_docs(45, title="tied", year=2000)
    await bulk_index(simple_repository, docs)

    returned = [
        hit.id
        async for page in simple_repository.scan_with_query_string(
            "title:tied", page_size=10, sort=["year"]
        )
        for hit in page.hits
    ]

    assert len(returned) == 45
    assert {str(rid) for rid in returned} == {str(doc.id) for doc in docs}


async def test_scan_limit_trims_final_page(simple_repository: SimpleRepository):
    """A limit that is not a page multiple trims the final page exactly."""
    await bulk_index(simple_repository, build_simple_docs(55, title="scan"))

    pages = [
        page
        async for page in simple_repository.scan_with_query_string(
            "title:scan", page_size=20, limit=25
        )
    ]

    assert [len(page.hits) for page in pages] == [20, 5]
    assert sum(len(page.hits) for page in pages) == 25


async def test_scan_limit_exceeding_total_returns_all(
    simple_repository: SimpleRepository,
):
    """A limit larger than the result set returns everything and stops."""
    await bulk_index(simple_repository, build_simple_docs(10, title="scan"))

    returned = [
        hit
        async for page in simple_repository.scan_with_query_string(
            "title:scan", page_size=20, limit=1000
        )
        for hit in page.hits
    ]

    assert len(returned) == 10


async def test_scan_exceeds_result_window(simple_repository: SimpleRepository):
    """Scan pages past ES's 10,000 from+size result window."""
    count = ES_MAX_PAGE_SIZE + 50
    await bulk_index(simple_repository, build_simple_docs(count, title="big"))

    pages = [
        page
        async for page in simple_repository.scan_with_query_string(
            "title:big", page_size=ES_MAX_PAGE_SIZE
        )
    ]

    assert [len(page.hits) for page in pages] == [ES_MAX_PAGE_SIZE, 50]
    assert pages[0].total.value == count
    assert pages[0].total.relation == "eq"


async def test_scan_parse_document(simple_repository: SimpleRepository):
    """parse_document=True hydrates domain models on scanned hits."""
    await bulk_index(simple_repository, build_simple_docs(3, title="hydrate"))

    pages = [
        page
        async for page in simple_repository.scan_with_query_string(
            "title:hydrate", parse_document=True
        )
    ]

    hits = [hit for page in pages for hit in page.hits]
    assert len(hits) == 3
    assert all(isinstance(hit.document, SimpleDomainModel) for hit in hits)
    assert all(
        hit.document.title == "hydrate"
        for hit in hits
        if isinstance(hit.document, SimpleDomainModel)
    )


@pytest.mark.parametrize("page_size", [0, -1, ES_MAX_PAGE_SIZE + 1])
async def test_scan_rejects_invalid_page_size(
    simple_repository: SimpleRepository, page_size: int
):
    """page_size must sit within [1, ES_MAX_PAGE_SIZE]."""
    with pytest.raises(ESError):
        await anext(
            simple_repository.scan_with_query_string("title:scan", page_size=page_size)
        )


async def test_scan_rejects_invalid_limit(simple_repository: SimpleRepository):
    """A non-positive limit is rejected."""
    with pytest.raises(ESError):
        await anext(simple_repository.scan_with_query_string("title:scan", limit=0))


async def test_scan_closes_pit_on_early_exit(
    simple_repository: SimpleRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """Abandoning the scan mid-iteration still closes the PIT."""
    await bulk_index(simple_repository, build_simple_docs(30, title="scan"))

    close_calls: list[dict] = []
    original_close = simple_repository._client.close_point_in_time  # noqa: SLF001

    async def spy_close(**kwargs: Any) -> Any:
        close_calls.append(kwargs)
        return await original_close(**kwargs)

    monkeypatch.setattr(
        simple_repository._client,  # noqa: SLF001
        "close_point_in_time",
        spy_close,
    )

    scan = simple_repository.scan_with_query_string("title:scan", page_size=10)
    await anext(scan)
    await scan.aclose()

    assert len(close_calls) == 1


async def test_scan_closes_pit_on_error(
    simple_repository: SimpleRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """An error mid-scan still closes the PIT (the DSL CM trap)."""
    await bulk_index(simple_repository, build_simple_docs(30, title="scan"))

    close_calls: list[dict] = []
    original_close = simple_repository._client.close_point_in_time  # noqa: SLF001

    async def spy_close(**kwargs: Any) -> Any:
        close_calls.append(kwargs)
        return await original_close(**kwargs)

    monkeypatch.setattr(
        simple_repository._client,  # noqa: SLF001
        "close_point_in_time",
        spy_close,
    )

    call_count = {"n": 0}
    original_execute = simple_repository._execute_search  # noqa: SLF001

    async def failing_execute(search: Any) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 2:
            msg = "boom"
            raise RuntimeError(msg)
        return await original_execute(search)

    monkeypatch.setattr(simple_repository, "_execute_search", failing_execute)

    async def drain() -> None:
        async for _ in simple_repository.scan_with_query_string(
            "title:scan", page_size=10
        ):
            pass

    with pytest.raises(RuntimeError, match="boom"):
        await drain()

    assert len(close_calls) == 1


def test_compose_query_scored_bare(simple_repository: SimpleRepository):
    """A scored query with no filters is a bare query_string."""
    query = simple_repository._compose_query("title:x", None, None)  # noqa: SLF001
    assert query.to_dict() == {"query_string": {"query": "title:x"}}


def test_compose_query_scored_keeps_query_in_must(simple_repository: SimpleRepository):
    """Scored: the query_string stays in `must` (scored) alongside filters."""
    query = simple_repository._compose_query(  # noqa: SLF001
        "title:x", None, [Term(year=2000)]
    )
    assert query.to_dict() == {
        "bool": {
            "must": [{"query_string": {"query": "title:x"}}],
            "filter": [{"term": {"year": 2000}}],
        }
    }


def test_compose_query_non_scoring_uses_filter_context(
    simple_repository: SimpleRepository,
):
    """`score=False` drops the query_string into filter context (no scoring)."""
    query = simple_repository._compose_query(  # noqa: SLF001
        "title:x", None, [Term(year=2000)], score=False
    )
    assert query.to_dict() == {
        "bool": {
            "filter": [
                {"query_string": {"query": "title:x"}},
                {"term": {"year": 2000}},
            ]
        }
    }


async def test_count_with_query_string_is_exact(simple_repository: SimpleRepository):
    """count returns the exact number of matches."""
    await bulk_index(simple_repository, build_simple_docs(7, title="countme"))
    total = await simple_repository.count_with_query_string("title:countme")
    assert total.value == 7
    assert total.relation == "eq"


async def test_count_exceeds_result_window(simple_repository: SimpleRepository):
    """count is exact beyond ES's 10,000 window, unlike a bounded search."""
    count = ES_MAX_PAGE_SIZE + 1
    await bulk_index(simple_repository, build_simple_docs(count, title="many"))
    total = await simple_repository.count_with_query_string("title:many")
    assert total.value == count
    assert total.relation == "eq"


async def test_scan_non_scoring_returns_all(simple_repository: SimpleRepository):
    """A non-scoring scan (filter context) still returns every match."""
    docs = build_simple_docs(30, title="noscore")
    await bulk_index(simple_repository, docs)

    returned = [
        hit.id
        async for page in simple_repository.scan_with_query_string(
            "title:noscore", page_size=10, score=False
        )
        for hit in page.hits
    ]

    assert {str(rid) for rid in returned} == {str(doc.id) for doc in docs}


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
        id=uuid7(),
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


@pytest.mark.usefixtures("linked_data_ref")
async def test_reference_count(reference_repository: ReferenceESRepository):
    """`ReferenceESRepository.count` returns an exact match total for a query."""
    total = await reference_repository.count(
        SearchQuery(query_string="_exists_:linked_data_concepts")
    )
    assert total.value == 1
    assert total.relation == "eq"


async def test_reference_scan_non_scoring_returns_all(
    reference_repository: ReferenceESRepository,
    linked_data_ref: str,
):
    """A non-scoring reference scan orders by the id tiebreaker and returns matches."""
    returned = [
        hit.id
        async for page in reference_repository.scan(
            SearchQuery(query_string="_exists_:linked_data_concepts"), score=False
        )
        for hit in page.hits
    ]
    assert [str(rid) for rid in returned] == [linked_data_ref]
