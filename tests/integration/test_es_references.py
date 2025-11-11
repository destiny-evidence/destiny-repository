# ruff: noqa: E501. These lines are just gonna be long.
"""Integration tests for references in Elasticsearch."""

import uuid
from collections.abc import AsyncGenerator

import destiny_sdk
import pytest
from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AuthorPosition,
    Authorship,
    BibliographicMetadataEnhancement,
    EnhancementType,
)
from elasticsearch import AsyncElasticsearch

from app.core.exceptions import ESNotFoundError, ESQueryError
from app.domain.references.models.models import (
    Enhancement,
    Reference,
    ReferenceWithChangeset,
    RobotAutomation,
)
from app.domain.references.models.projections import (
    ReferenceSearchFieldsProjection,
)
from app.domain.references.repository import (
    ReferenceESRepository,
    RobotAutomationESRepository,
)
from app.utils.time_and_date import utc_now
from tests.factories import (
    AbstractContentEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    ReferenceFactory,
)


@pytest.fixture
async def es_reference_repository(
    es_client: AsyncElasticsearch,
) -> ReferenceESRepository:
    """Fixture to create an Elasticsearch reference repository."""
    return ReferenceESRepository(
        client=es_client,
    )


@pytest.fixture
async def es_robot_automation_repository(
    es_client: AsyncElasticsearch,
) -> RobotAutomationESRepository:
    """Fixture to create an Elasticsearch robot automation repository."""
    return RobotAutomationESRepository(
        client=es_client,
    )


@pytest.fixture
async def reference() -> Reference:
    """Fixture to create a sample reference."""
    return Reference(
        id=(r := uuid.uuid4()),
        visibility="public",
        identifiers=[
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "identifier": {
                    "identifier_type": "pm_id",
                    "identifier": 123,
                },
            },
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "identifier": {
                    "identifier_type": "doi",
                    "identifier": "10.1000/xyz123",
                },
            },
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "identifier": {
                    "identifier_type": "other",
                    "other_identifier_name": "isbn",
                    "identifier": "978-3-16-148410-0",
                },
            },
        ],
        enhancements=[
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "created_at": utc_now(),
                "content": {
                    "enhancement_type": "annotation",
                    "annotations": [
                        {
                            "annotation_type": "boolean",
                            "scheme": "openalex:topic",
                            "label": "test_label",
                            "value": True,
                            "score": 0.95,
                            "data": {"foo": "bar"},
                        }
                    ],
                },
                "source": "test_source",
                "visibility": "public",
            },
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "created_at": utc_now(),
                "content": {
                    "enhancement_type": "location",
                    "locations": [
                        {
                            "landing_page_url": "https://example.com",
                        }
                    ],
                },
                "source": "test_source",
                "visibility": "public",
            },
            {
                "id": uuid.uuid4(),
                "reference_id": r,
                "created_at": utc_now(),
                "content": {
                    "enhancement_type": "bibliographic",
                    "title": " Sample reference Title with whitespace and a funny charactér ",
                    "authorship": [
                        {
                            "display_name": "bMiddle author",
                            "position": destiny_sdk.enhancements.AuthorPosition.MIDDLE,
                        },
                        {
                            "display_name": "aMiddlé author",
                            "position": destiny_sdk.enhancements.AuthorPosition.MIDDLE,
                        },
                        {
                            "display_name": "Last author",
                            "position": destiny_sdk.enhancements.AuthorPosition.LAST,
                        },
                        {
                            "display_name": "First author ",
                            "position": destiny_sdk.enhancements.AuthorPosition.FIRST,
                        },
                    ],
                    "publication_year": 2023,
                },
                "source": "test_source",
                "visibility": "public",
            },
        ],
        duplicate_decision={
            "reference_id": r,
            "duplicate_determination": "canonical",
            "active_decision": True,
        },
    )


@pytest.fixture
async def abstract_robot_automation() -> RobotAutomation:
    """
    Fixture to create a sample abstract robot automation.

    This query matches on references that have had a DOI identifier added and
    do not have an abstract enhancement.
    """
    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "changeset.identifiers",
                            "query": {
                                "term": {"changeset.identifiers.identifier_type": "doi"}
                            },
                        }
                    }
                ],
                "must_not": [
                    {
                        "nested": {
                            "path": "reference.enhancements",
                            "query": {
                                "term": {
                                    "reference.enhancements.content.enhancement_type": "abstract"
                                }
                            },
                        }
                    }
                ],
            }
        },
    )


@pytest.fixture
async def in_out_robot_automation() -> RobotAutomation:
    """
    Fixture to create a sample in-out robot automation.

    This query matches on changesets that add an abstract enhancement.
    """
    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "changeset.enhancements",
                            "query": {
                                "term": {
                                    "changeset.enhancements.content.enhancement_type": "abstract"
                                }
                            },
                        }
                    },
                ],
            }
        },
    )


@pytest.fixture
async def taxonomy_robot_automation() -> RobotAutomation:
    """
    Fixture to create a sample taxonomy robot automation.

    This query matches on changesets that add a positive in/out annotation enhancement.
    """
    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "changeset.enhancements.content.annotations",
                            "query": {
                                "bool": {
                                    "must": [
                                        {
                                            "term": {
                                                "changeset.enhancements.content.annotations.label": "in_destiny_domain"
                                            }
                                        },
                                        {
                                            "term": {
                                                "changeset.enhancements.content.annotations.annotation_type": "boolean"
                                            }
                                        },
                                        {
                                            "term": {
                                                "changeset.enhancements.content.annotations.value": True
                                            }
                                        },
                                    ]
                                }
                            },
                        }
                    },
                ],
            }
        },
    )


async def test_es_repository_cycle(
    es_reference_repository: ReferenceESRepository, reference: Reference
):
    """Test saving and getting a reference by primary key from Elasticsearch."""
    bibliographic_enhancement: destiny_sdk.enhancements.BibliographicMetadataEnhancement = reference.enhancements[
        2
    ].content  # type: ignore[index]

    await es_reference_repository.add(reference)

    es_reference = await es_reference_repository.get_by_pk(reference.id)

    assert es_reference.id == reference.id
    assert es_reference.visibility == "public"
    assert len(es_reference.identifiers or []) == 3
    assert len(es_reference.enhancements or []) == 3
    # Check that ids are preserved
    assert {enhancement.id for enhancement in es_reference.enhancements or []} == {
        enhancement.id for enhancement in reference.enhancements or []
    }

    # Check the ES projections themselves
    client = es_reference_repository._client  # noqa: SLF001
    await client.indices.refresh(
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )
    raw_es_reference = (
        await client.get(
            index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
            id=str(reference.id),
        )
    )["_source"]

    assert (
        raw_es_reference["publication_year"]
        == bibliographic_enhancement.publication_year  # type: ignore  # noqa: PGH003
    )
    assert (
        raw_es_reference["title"]
        == "Sample reference Title with whitespace and a funny charactér"
    )
    assert raw_es_reference["authors"] == [
        "First author",
        "aMiddlé author",
        "bMiddle author",
        "Last author",
    ]


async def test_es_repository_not_found(
    es_reference_repository: ReferenceESRepository,
):
    """Test that getting a non-existent reference raises an error."""
    with pytest.raises(ESNotFoundError):
        await es_reference_repository.get_by_pk(uuid.uuid4())


async def test_es_repository_update_existing(
    es_reference_repository: ReferenceESRepository, reference: Reference
):
    """Test updating an existing reference in Elasticsearch."""
    await es_reference_repository.add(reference)
    await test_es_repository_cycle(es_reference_repository, reference)

    # Modify the reference
    reference = reference.model_copy(
        update={"visibility": "restricted", "enhancements": []}
    )
    await es_reference_repository.add(reference)
    updated_reference = await es_reference_repository.get_by_pk(reference.id)

    assert updated_reference.id == reference.id
    assert updated_reference.visibility == "restricted"
    assert len(updated_reference.identifiers or []) == 3
    assert len(updated_reference.enhancements or []) == 0


async def test_add_bulk(
    es_reference_repository: ReferenceESRepository, reference: Reference
):
    """Test bulk adding multiple references."""
    ref_ids = []

    async def yield_reference() -> AsyncGenerator[Reference, None]:
        for _ in range(5):
            ref_ids.append(uuid.uuid4())
            yield reference.model_copy(
                update={"visibility": "public", "id": ref_ids[-1]}
            )

    await es_reference_repository.add_bulk(yield_reference())

    for ref_id in ref_ids:
        retrieved_ref = await es_reference_repository.get_by_pk(ref_id)
        assert retrieved_ref.visibility == "public"
        assert len(retrieved_ref.identifiers or []) == 3
        assert len(retrieved_ref.enhancements or []) == 3


async def test_robot_automation_percolation(
    es_robot_automation_repository: RobotAutomationESRepository,
    reference: Reference,
    abstract_robot_automation: RobotAutomation,
    in_out_robot_automation: RobotAutomation,
    taxonomy_robot_automation: RobotAutomation,
):
    """Test robot automation percolation."""
    # Seed repository
    await es_robot_automation_repository.add(abstract_robot_automation)
    await es_robot_automation_repository.add(in_out_robot_automation)
    await es_robot_automation_repository.add(taxonomy_robot_automation)

    # Build a bunch of reference/enhancement variants
    abstract_enhancement = Enhancement(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        content={
            "enhancement_type": "abstract",
            "abstract": "This is a test abstract.",
            "process": "closed_api",
        },
        source="test_source",
        visibility="public",
    )
    positive_in_out_annotation_enhancement = Enhancement(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "dummy-scheme",
                    "label": "in_destiny_domain",
                    "value": True,
                }
            ],
        },
        source="test_source",
        visibility="public",
    )
    negative_in_out_annotation_enhancement = Enhancement(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "dummy-scheme",
                    "label": "in_destiny_domain",
                    "value": False,
                }
            ],
        },
        source="test_source",
        visibility="public",
    )
    reference_no_abstract = reference.model_copy()
    reference_with_abstract = reference.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [*reference.enhancements, abstract_enhancement],  # type: ignore[misc]
        }
    )
    reference_no_abstract_no_doi = reference_no_abstract.model_copy(
        update={
            "id": uuid.uuid4(),
            "identifiers": [
                identifier
                for identifier in (reference_no_abstract.identifiers or [])
                if identifier.identifier.identifier_type != "doi"
            ],
        }
    )
    # Add the abstract enhancement to the reference with no abstract
    reference_no_abstract_in_domain = reference.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                *reference.enhancements,
                positive_in_out_annotation_enhancement,
            ],  # type: ignore[misc]
        }
    )
    reference_with_abstract_in_domain = reference_with_abstract.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                *reference_with_abstract.enhancements,
                positive_in_out_annotation_enhancement,
            ],  # type: ignore[misc]
        }
    )
    reference_with_abstract_out_of_domain = reference_with_abstract.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                *reference_with_abstract.enhancements,
                negative_in_out_annotation_enhancement,
            ],  # type: ignore[misc]
        }
    )

    percolatable_documents: list[ReferenceWithChangeset] = [
        ReferenceWithChangeset(
            **reference_no_abstract.model_dump(), changeset=reference_no_abstract
        ),
        ReferenceWithChangeset(
            **reference_with_abstract.model_dump(),
            changeset=reference_with_abstract,
        ),
        ReferenceWithChangeset(
            **reference_no_abstract_no_doi.model_dump(),
            changeset=reference_no_abstract_no_doi,
        ),
        ReferenceWithChangeset(
            **reference_no_abstract_in_domain.model_dump(),
            changeset=reference_no_abstract_in_domain,
        ),
        ReferenceWithChangeset(
            **reference_with_abstract_in_domain.model_dump(),
            changeset=reference_with_abstract_in_domain,
        ),
        ReferenceWithChangeset(
            **reference_with_abstract_out_of_domain.model_dump(),
            changeset=reference_with_abstract_out_of_domain,
        ),
        ReferenceWithChangeset(
            id=abstract_enhancement.reference_id,
            changeset=Reference(enhancements=[abstract_enhancement]),
        ),
        ReferenceWithChangeset(
            id=positive_in_out_annotation_enhancement.reference_id,
            enhancements=[abstract_enhancement],
            changeset=Reference(enhancements=[positive_in_out_annotation_enhancement]),
        ),
        ReferenceWithChangeset(
            id=negative_in_out_annotation_enhancement.reference_id,
            enhancements=[abstract_enhancement],
            changeset=Reference(enhancements=[negative_in_out_annotation_enhancement]),
        ),
    ]

    # This is needed when running in quick succession to ensure the index is ready
    # for percolation.
    await es_robot_automation_repository._client.indices.refresh(  # noqa: SLF001
        index=es_robot_automation_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    results = await es_robot_automation_repository.percolate(
        percolatable_documents,
    )

    # Check each robot automation
    for result in results:
        if result.robot_id == abstract_robot_automation.robot_id:
            # Everything with a DOI and no abstract
            assert result.reference_ids == {
                reference_no_abstract.id,
                reference_no_abstract_in_domain.id,
            }
        elif result.robot_id == in_out_robot_automation.robot_id:
            # Everything with an abstract in the changeset
            assert result.reference_ids == {
                reference_with_abstract.id,
                reference_with_abstract_in_domain.id,
                reference_with_abstract_out_of_domain.id,
                abstract_enhancement.reference_id,
            }
        elif result.robot_id == taxonomy_robot_automation.robot_id:
            # Everything with a positive in/out annotation
            assert result.reference_ids == {
                reference_no_abstract_in_domain.id,
                reference_with_abstract_in_domain.id,
                positive_in_out_annotation_enhancement.reference_id,
            }
        else:
            msg = f"Unexpected robot ID: {result.robot_id}"
            raise ValueError(msg)


async def test_canonical_candidate_search(
    es_reference_repository: ReferenceESRepository, reference: Reference
):
    """Test searching for candidate canonical references by fingerprint."""
    # Create two similar references that should match the fingerprint
    matching_ref1 = reference.model_copy(update={"id": uuid.uuid4()})

    # Similar reference with slight variations
    matching_ref2 = reference.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                enhancement.model_copy(
                    update={
                        "id": uuid.uuid4(),
                        "reference_id": uuid.uuid4(),
                        "content": (
                            enhancement.content.model_copy(
                                update={
                                    "title": "Sample Reference Title with Whitespace",
                                }
                            )
                            if enhancement.content.enhancement_type
                            == EnhancementType.BIBLIOGRAPHIC
                            else enhancement.content
                        ),
                    }
                )
                for enhancement in (reference.enhancements or [])
            ],
        }
    )

    # Create a completely different reference that should not match
    non_matching_ref = reference.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                enhancement.model_copy(
                    update={
                        "id": uuid.uuid4(),
                        "reference_id": uuid.uuid4(),
                        "content": (
                            enhancement.content.model_copy(
                                update={
                                    "title": "Completely Different Paper Title",
                                    "authorship": [
                                        Authorship(
                                            display_name="Different Author",
                                            position=AuthorPosition.FIRST,
                                        )
                                    ],
                                    "publication_year": 2020,
                                }
                            )
                            if enhancement.content.enhancement_type
                            == EnhancementType.BIBLIOGRAPHIC
                            else enhancement.content
                        ),
                    }
                )
                for enhancement in (reference.enhancements or [])
            ],
        }
    )

    # Add all references to the repository
    await es_reference_repository.add(matching_ref1)
    await es_reference_repository.add(matching_ref2)
    await es_reference_repository.add(non_matching_ref)

    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name  # noqa: SLF001
    )

    matching_search_fields = (
        ReferenceSearchFieldsProjection.get_canonical_candidate_search_fields(
            matching_ref1
        )
    )

    # Test the search_for_candidate_canonicals method
    results = await es_reference_repository.search_for_candidate_canonicals(
        search_fields=matching_search_fields,
        reference_id=matching_ref1.id,
    )

    assert {reference.id for reference in results} == {matching_ref2.id}

    non_matching_search_fields = (
        ReferenceSearchFieldsProjection.get_canonical_candidate_search_fields(
            non_matching_ref
        )
    )

    results = await es_reference_repository.search_for_candidate_canonicals(
        non_matching_search_fields,
        reference_id=non_matching_ref.id,
    )
    assert not results


@pytest.mark.parametrize(
    ("query", "should_match"),
    [
        # Basic field search
        ("title:test", True),
        ("title:nonexistent", False),
        # Wildcard search
        ("title:test*", True),
        # Boolean operators
        ("title:test AND publication_year:2023", True),
        ("title:test OR title:nonexistent", True),
        ("title:test NOT abstract:seal", True),
        # Field existence
        ("_exists_:title", True),
        ("_exists_:nonexistent_field", False),
        # Multi-field search
        ("test", True),
        # Phrase search
        ('"test paper"', True),
        # Range query
        ("publication_year:[2020 TO 2024]", True),
        # Slop
        ('"test paper and"~0', True),
        ('"paper all that"~3', True),
        ('"test missing"~1', False),
        # Fuzzy
        ("title:teest~1", True),
        ("title:unrelated~1", False),
        ("abstract:hippotamus~2", True),
        # Go crazy
        (
            "publication_year:[2020 TO 2025] "
            'AND "test and all"~2 '
            "AND title:teest~1 "
            "AND NOT impossible_field:foobar",
            True,
        ),
        (
            "publication_year:[2020 TO 2025] "
            'AND "test and all"~2 '
            "AND title:teest "
            "AND NOT impossible_field:foobar",
            False,
        ),
    ],
)
async def test_query_string_search_scenarios(
    es_reference_repository: ReferenceESRepository,
    query: str,
    *,
    should_match: bool,
):
    """Test various Lucene query syntax scenarios."""
    bibliographic_enhancement: BibliographicMetadataEnhancement = (
        BibliographicMetadataEnhancementFactory.build(
            title="test paper and all that",
            publication_year=2023,
        )
    )
    abstract_enhancement: AbstractContentEnhancement = (
        AbstractContentEnhancementFactory.build(
            abstract=(
                "This is a test abstract for the test paper. "
                "Abstract art is cool. Hippopotamus."
            ),
        )
    )
    reference = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(content=bibliographic_enhancement),
            EnhancementFactory.build(content=abstract_enhancement),
        ]
    )
    await es_reference_repository.add(reference)

    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name  # noqa: SLF001
    )

    results = await es_reference_repository.search_with_query_string(query)

    if should_match:
        assert len(results.hits) == 1
        assert results.total.value == 1
        assert results.hits[0].id == reference.id
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
        "publication_year:[2020 TO ]",  # Invalid range
        "title:foo^",  # Invalid boost
    ],
)
async def test_query_string_search_invalid_syntax(
    es_reference_repository: ReferenceESRepository,
    query: str,
):
    """Test that invalid Lucene query syntax raises an error."""
    with pytest.raises(ESQueryError):
        await es_reference_repository.search_with_query_string(query)


async def test_query_string_search_many_results(
    es_reference_repository: ReferenceESRepository,
):
    """Test searching for references using a query string that returns many results."""
    bibliographic_enhancement: BibliographicMetadataEnhancement = (
        BibliographicMetadataEnhancementFactory.build()
    )

    async def _insert_references_batch() -> None:
        references = ReferenceFactory.build_batch(
            6_000,
            enhancements=[EnhancementFactory.build(content=bibliographic_enhancement)],
        )

        async def reference_generator(
            references: list[Reference],
        ) -> AsyncGenerator[Reference, None]:
            for reference in references:
                yield reference

        await es_reference_repository.add_bulk(reference_generator(references))
        await es_reference_repository._client.indices.refresh(  # noqa: SLF001
            index=es_reference_repository._persistence_cls.Index.name  # noqa: SLF001
        )

    await _insert_references_batch()

    # Search by title keyword
    results = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}"
    )
    # Default page size
    assert len(results.hits) == 20
    assert results.total.value == 6_000
    assert results.total.relation == "eq"

    await _insert_references_batch()

    results = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}"
    )
    assert len(results.hits) == 20
    # Default elasticsearch cap
    assert results.total.value == 10_000
    assert results.total.relation == "gte"


async def test_query_string_search_with_fields(
    es_reference_repository: ReferenceESRepository,
):
    """Test searching with specific fields restricts search scope."""
    # Create references with different field values
    bibliographic_enhancement_1: BibliographicMetadataEnhancement = (
        BibliographicMetadataEnhancementFactory.build(
            title="unique title searchterm",
            publication_year=2023,
        )
    )
    abstract_enhancement_1: AbstractContentEnhancement = AbstractContentEnhancementFactory.build(
        abstract="This abstract does not contain the special term, but it does contain the word spondonicle.",
    )
    reference_with_title_match = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(content=bibliographic_enhancement_1),
            EnhancementFactory.build(content=abstract_enhancement_1),
        ]
    )

    await es_reference_repository.add(reference_with_title_match)

    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name  # noqa: SLF001
    )

    # Search restricted to title field - should only find reference with title match
    results_title_only = await es_reference_repository.search_with_query_string(
        "searchterm AND spondonicle",
        fields=["title", "abstract"],
    )
    assert len(results_title_only.hits) == 1
    assert results_title_only.hits[0].id == reference_with_title_match.id

    # Search restricted to publication_year field - should find nothing
    results_year_only = await es_reference_repository.search_with_query_string(
        "searchterm",
        fields=["publication_year"],
    )
    assert len(results_year_only.hits) == 0


async def test_query_string_search_pagination(
    es_reference_repository: ReferenceESRepository,
):
    """Test pagination in query string search."""
    bibliographic_enhancement: BibliographicMetadataEnhancement = (
        BibliographicMetadataEnhancementFactory.build()
    )
    reference_ids = set()

    async def _insert_references_batch() -> None:
        references = ReferenceFactory.build_batch(
            55,
            enhancements=[EnhancementFactory.build(content=bibliographic_enhancement)],
        )

        async def reference_generator(
            references: list[Reference],
        ) -> AsyncGenerator[Reference, None]:
            for reference in references:
                reference_ids.add(reference.id)
                yield reference

        await es_reference_repository.add_bulk(reference_generator(references))
        await es_reference_repository._client.indices.refresh(  # noqa: SLF001
            index=es_reference_repository._persistence_cls.Index.name  # noqa: SLF001
        )

    await _insert_references_batch()

    results_page_1 = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}",
        page=1,
        page_size=20,
    )
    assert len(results_page_1.hits) == 20
    assert results_page_1.total.value == 55
    assert results_page_1.total.relation == "eq"

    results_page_2 = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}",
        page=2,
        page_size=20,
    )
    assert len(results_page_2.hits) == 20

    results_page_3 = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}",
        page=3,
        page_size=20,
    )
    assert len(results_page_3.hits) == 15

    assert {
        hit.id
        for hit in results_page_1.hits + results_page_2.hits + results_page_3.hits
    } == reference_ids

    results_page_4 = await es_reference_repository.search_with_query_string(
        f"title:{bibliographic_enhancement.title}",
        page=4,
        page_size=20,
    )
    assert len(results_page_4.hits) == 0
