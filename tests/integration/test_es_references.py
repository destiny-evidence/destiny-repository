"""Integration tests for references in Elasticsearch."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import destiny_sdk
import pytest
from destiny_sdk.enhancements import AuthorPosition, Authorship
from elasticsearch import AsyncElasticsearch

from app.core.exceptions import ESNotFoundError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementType,
    Reference,
    RobotAutomation,
)
from app.domain.references.models.projections import CandidacyFingerprintProjection
from app.domain.references.repository import (
    ReferenceESRepository,
    RobotAutomationESRepository,
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
                "content": {
                    "enhancement_type": "bibliographic",
                    "title": " Sample reference Title with whitespace and a funny charactér ",
                    "authorship": [
                        {
                            "display_name": "bMiddle author",
                            "position": destiny_sdk.enhancements.AuthorPosition.MIDDLE,
                        },
                        {
                            "display_name": "aMiddlé author",
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
    )


@pytest.fixture
async def abstract_robot_automation() -> RobotAutomation:
    """
    Fixture to create a sample abstract robot automation.

    This query matches on references that have a DOI identifier
    and do not have an abstract enhancement.
    """
    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "reference.identifiers",
                            "query": {
                                "term": {"reference.identifiers.identifier_type": "DOI"}
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

    This query matches on references that have an abstract and on enhancements which
    are abstracts themselves.
    """
    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "reference.enhancements",
                            "query": {
                                "term": {
                                    "reference.enhancements.content.enhancement_type": "abstract"
                                }
                            },
                        }
                    },
                    {"term": {"enhancement.content.enhancement_type": "abstract"}},
                ],
                "minimum_should_match": 1,
            }
        },
    )


@pytest.fixture
async def taxonomy_robot_automation() -> RobotAutomation:
    """
    Fixture to create a sample taxonomy robot automation.

    This query matches on references that have a positive in/out annotation and
    on enhancements which are annotations themselves.
    """

    # ruff: noqa: E501
    def get_annotation_filter(prefix: str) -> dict[str, Any]:
        return {
            "nested": {
                "path": f"{prefix}.content.annotations",
                "query": {
                    "bool": {
                        "must": [
                            {
                                "term": {
                                    f"{prefix}.content.annotations.label": "in_destiny_domain"
                                }
                            },
                            {
                                "bool": {
                                    "should": [
                                        {
                                            "bool": {
                                                "must_not": [
                                                    {
                                                        "term": {
                                                            f"{prefix}.content.annotations.annotation_type": "boolean"
                                                        }
                                                    }
                                                ]
                                            }
                                        },
                                        {
                                            "bool": {
                                                "must": [
                                                    {
                                                        "term": {
                                                            f"{prefix}.content.annotations.annotation_type": "boolean"
                                                        }
                                                    },
                                                    {
                                                        "term": {
                                                            f"{prefix}.content.annotations.value": True
                                                        }
                                                    },
                                                ]
                                            }
                                        },
                                    ]
                                }
                            },
                        ]
                    }
                },
            }
        }

    return RobotAutomation(
        robot_id=uuid.uuid4(),
        query={
            "bool": {
                "should": [
                    get_annotation_filter("reference.enhancements"),
                    get_annotation_filter("enhancement"),
                ],
                "minimum_should_match": 1,
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
        == "Sample reference Title with whitespace and a funny charactér"
    )
    assert raw_es_reference["authors"] == [
        "First author",
        "aMiddlé author",
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


async def test_bulk_add(
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
    existential_in_out_annotation_enhancement = Enhancement(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "score",
                    "scheme": "dummy-scheme",
                    "label": "in_destiny_domain",
                    "score": 0.75,
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
    reference_with_abstract_in_domain_two = reference_with_abstract.model_copy(
        update={
            "id": uuid.uuid4(),
            "enhancements": [
                *reference_with_abstract.enhancements,
                existential_in_out_annotation_enhancement,
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

    percolatable_documents: list[Reference | Enhancement] = [
        reference_no_abstract,
        reference_with_abstract,
        reference_no_abstract_no_doi,
        reference_no_abstract_in_domain,
        reference_with_abstract_in_domain,
        reference_with_abstract_in_domain_two,
        reference_with_abstract_out_of_domain,
        abstract_enhancement,
        positive_in_out_annotation_enhancement,
        negative_in_out_annotation_enhancement,
        existential_in_out_annotation_enhancement,
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
            # Everything with an abstract
            assert result.reference_ids == {
                reference_with_abstract.id,
                reference_with_abstract_in_domain.id,
                reference_with_abstract_in_domain_two.id,
                reference_with_abstract_out_of_domain.id,
                abstract_enhancement.reference_id,
            }
        elif result.robot_id == taxonomy_robot_automation.robot_id:
            # Everything with a positive in/out annotation
            assert result.reference_ids == {
                reference_no_abstract_in_domain.id,
                reference_with_abstract_in_domain.id,
                reference_with_abstract_in_domain_two.id,
                positive_in_out_annotation_enhancement.reference_id,
                existential_in_out_annotation_enhancement.reference_id,
            }
        else:
            msg = f"Unexpected robot ID: {result.robot_id}"
            raise ValueError(msg)


async def test_search_fingerprints(
    es_reference_repository: ReferenceESRepository, reference: Reference
):
    """Test searching for candidate duplicate references by fingerprint."""
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

    searches = [
        CandidacyFingerprintProjection.get_from_reference(matching_ref1),
        CandidacyFingerprintProjection.get_from_reference(non_matching_ref),
    ]
    # Test the search_fingerprints method
    results = await es_reference_repository.search_fingerprints(searches)

    # Order is important, check it
    assert [r.fingerprint for r in results] == searches

    assert {r.id for r in results[0].candidate_duplicates} == {
        matching_ref1.id,
        matching_ref2.id,
    }
    assert {r.id for r in results[1].candidate_duplicates} == {non_matching_ref.id}
