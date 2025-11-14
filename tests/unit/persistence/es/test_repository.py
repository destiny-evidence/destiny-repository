"""Unit tests for Elasticsearch repository query string search functionality."""

from collections.abc import AsyncGenerator
from typing import Self
from uuid import uuid4

import pytest
from elasticsearch import AsyncElasticsearch
from elasticsearch.dsl.field import Integer, Text
from elasticsearch.helpers import async_bulk

from app.core.exceptions import ESQueryError
from app.domain.base import SQLAttributeMixin
from app.persistence.es.persistence import GenericESPersistence
from app.persistence.es.repository import GenericAsyncESRepository


class DomainSimpleDoc(SQLAttributeMixin):
    """Simple domain document with basic fields."""

    title: str
    year: int
    content: str


class SimpleDoc(GenericESPersistence):
    """Simple test document with basic fields."""

    title = Text()
    year = Integer()
    content = Text()

    class Index:
        name = "test_simple"

    def to_domain(self) -> DomainSimpleDoc:
        """Convert to simple domain dict."""
        return DomainSimpleDoc(
            id=self.meta.id,
            title=self.title,
            year=self.year,
            content=self.content,
        )

    @classmethod
    def from_domain(cls, domain_model: DomainSimpleDoc) -> Self:
        """Create from simple domain dict."""
        return cls(
            meta={"id": domain_model.id},
            title=domain_model.title,
            year=domain_model.year,
            content=domain_model.content,
        )


class SimpleRepository(GenericAsyncESRepository[DomainSimpleDoc, SimpleDoc]):
    """Simple repository for testing."""

    def __init__(self, client: AsyncElasticsearch):
        super().__init__(
            client=client,
            domain_cls=DomainSimpleDoc,
            persistence_cls=SimpleDoc,
        )


@pytest.fixture
async def simple_repository(
    es_client: AsyncElasticsearch,
) -> AsyncGenerator[SimpleRepository, None]:
    """Create a simple repository with test index."""
    # Initialize the index
    await SimpleDoc.init(using=es_client)

    repo = SimpleRepository(client=es_client)
    yield repo

    # Cleanup
    await es_client.indices.delete(index="test_simple", ignore=[404])


async def create_simple_doc(
    repository: SimpleRepository,
    title: str,
    year: int,
    content: str,
) -> str:
    """Helper to create and index a simple document."""
    doc_id = str(uuid4())
    doc = SimpleDoc(title=title, year=year, content=content, meta={"id": doc_id})
    await doc.save(using=repository._client)  # noqa: SLF001
    return doc_id


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
            meta={"id": uuid4()},
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

    # Search restricted to year field only - should find nothing
    results_year_only = await simple_repository.search_with_query_string(
        "searchterm",
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
            meta={"id": uuid4()},
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
