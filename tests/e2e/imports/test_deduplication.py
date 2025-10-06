"""End-to-end tests for import deduplication."""

import uuid
from collections.abc import Callable
from contextlib import _AsyncGeneratorContextManager

import httpx
import pytest
from destiny_sdk.enhancements import (
    Authorship,
    BibliographicMetadataEnhancement,
    BooleanAnnotation,
)
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import Retrying, stop_after_attempt, wait_fixed

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    PendingEnhancementStatus,
    Reference,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.robots.models.models import Robot
from tests.e2e.factories import (
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    ReferenceFactory,
)
from tests.e2e.utils import (
    TestPollingExhaustedError,
    import_references,
    poll_duplicate_process,
    poll_pending_enhancement,
    refresh_reference_index,
)


@pytest.fixture
def canonical_bibliographic_enhancement() -> BibliographicMetadataEnhancement:
    """Get a pre-defined bibliographic enhancement."""
    return BibliographicMetadataEnhancementFactory.build(
        title="A Study on the Effects of Testing",
        authorship=[
            Authorship(display_name="Jane Doe", position="first"),
            Authorship(display_name="John Smith", position="last"),
        ],
        publication_year=2025,
    )


@pytest.fixture
def automation_triggering_annotation() -> BooleanAnnotation:
    """Get a pre-defined annotation that triggers robot automation."""
    return BooleanAnnotationFactory.build(
        value=True,
        scheme="Trigger Robot Automation",
        label="test-robot-automation",
    )


@pytest.fixture
def automation_triggering_annotation_enhancement(
    automation_triggering_annotation: BooleanAnnotation,
) -> Enhancement:
    """Get a pre-defined enhancement that triggers robot automation."""
    return EnhancementFactory.build(
        content=AnnotationEnhancementFactory.build(
            annotations=[automation_triggering_annotation]
        ),
    )


@pytest.fixture
def canonical_reference(canonical_bibliographic_enhancement: Enhancement) -> Reference:
    """Get a pre-defined canonical reference."""
    return ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(content=canonical_bibliographic_enhancement),
            # Some other enhancement
            EnhancementFactory.build(),
        ],
        identifiers=[
            # Make sure we have at least one non-other identifier
            LinkedExternalIdentifierFactory.build(
                identifier=DOIIdentifierFactory.build()
            ),
            LinkedExternalIdentifierFactory.build(),
        ],
    )


@pytest.fixture
def duplicate_reference(
    canonical_reference: Reference,
    automation_triggering_annotation_enhancement: Enhancement,
) -> Reference:
    """Get a slightly mutated canonical reference to be a duplicate."""
    duplicate = canonical_reference.model_copy(deep=True)
    assert duplicate.enhancements
    assert duplicate.enhancements[0]
    assert isinstance(
        duplicate.enhancements[0].content, BibliographicMetadataEnhancement
    )
    duplicate.enhancements[0].content.title = "A Study on the Effects of Testing!"
    assert duplicate.enhancements[0].content.authorship
    duplicate.enhancements[0].content.authorship[0] = Authorship(
        display_name="Jayne Doe", position="first"
    )
    duplicate.enhancements.append(automation_triggering_annotation_enhancement)
    return duplicate


# ruff: noqa: E501
@pytest.fixture
async def robot_automation_on_specific_enhancement(
    destiny_client_v1: httpx.AsyncClient,
    robot: Robot,
    automation_triggering_annotation: BooleanAnnotation,
) -> uuid.UUID:
    """Create a robot automation that runs on specific enhancements."""
    response = await destiny_client_v1.post(
        "/enhancement-requests/automations/",
        json={
            "robot_id": str(robot.id),
            "query": {
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
                                                    "changeset.enhancements.content.annotations.label": automation_triggering_annotation.label
                                                }
                                            },
                                            {
                                                "term": {
                                                    "changeset.enhancements.content.annotations.scheme": automation_triggering_annotation.scheme
                                                }
                                            },
                                            {
                                                "term": {
                                                    "changeset.enhancements.content.annotations.value": automation_triggering_annotation.value
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
        },
    )
    assert response.status_code == 201
    return robot.id


async def test_import_exact_duplicate(
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
):
    """Test importing an exact duplicate reference."""
    await import_references(
        destiny_client_v1,
        pg_session,
        es_client,
        [canonical_reference],
        get_import_file_signed_url,
    )

    # Mutate to make it a subsetting reference
    exact_duplicate_reference = canonical_reference.model_copy(deep=True)
    assert exact_duplicate_reference.enhancements
    exact_duplicate_reference.enhancements.pop()
    exact_duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [exact_duplicate_reference],
            get_import_file_signed_url,
        )
    ).pop()
    duplicate_decision = await poll_duplicate_process(
        pg_session, exact_duplicate_reference_id
    )
    assert (
        duplicate_decision["duplicate_determination"]
        == DuplicateDetermination.EXACT_DUPLICATE
    )
    pg_result = await pg_session.execute(
        text("SELECT COUNT(*) FROM reference WHERE id=:id;"),
        {"id": exact_duplicate_reference_id},
    )
    assert pg_result.scalar_one() == 0


async def test_import_duplicate(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    duplicate_reference: Reference,
    robot_automation_on_specific_enhancement: uuid.UUID,
):
    """Test importing a duplicate reference."""
    canonical_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()

    # Mutate the canonical reference a bit to make sure it's not an exact duplicate.
    duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [duplicate_reference],
            get_import_file_signed_url,
        )
    ).pop()

    duplicate_decision = await poll_duplicate_process(
        pg_session, duplicate_reference_id
    )
    assert (
        duplicate_decision["duplicate_determination"]
        == DuplicateDetermination.DUPLICATE
    )
    assert duplicate_decision["canonical_reference_id"] == canonical_reference_id

    # Check that the Elasticsearch index contains only the canonical, with the near
    # duplicate's data merged in.
    es_result = await es_client.search(
        index=ReferenceDocument.Index.name,
        query={
            "terms": {
                "_id": [
                    str(canonical_reference_id),
                    str(duplicate_reference_id),
                ]
            }
        },
    )
    assert es_result["hits"]["total"]["value"] == 1
    assert es_result["hits"]["hits"][0]["_id"] == str(canonical_reference_id)
    es_source = es_result["hits"]["hits"][0]["_source"]
    assert es_source["duplicate_determination"] == "canonical"

    authors, titles = set(), set()
    for enhancement in es_source["enhancements"]:
        if enhancement["content"]["enhancement_type"] == "bibliographic":
            titles.add(enhancement["content"]["title"])
            for author in enhancement["content"]["authorship"]:
                authors.add(author["display_name"])
    assert titles >= {
        "A Study on the Effects of Testing",
        "A Study on the Effects of Testing!",
    }
    assert authors >= {"Jayne Doe", "Jane Doe", "John Smith"}

    # Finally, check that the robot automation was triggered on the canonical reference
    # by the near duplicate's annotation enhancement.
    pe = await poll_pending_enhancement(
        pg_session,
        reference_id=canonical_reference_id,
        robot_id=robot_automation_on_specific_enhancement,
    )
    assert pe["status"].casefold() == PendingEnhancementStatus.PENDING.casefold()
    assert not pe["robot_enhancement_batch_id"]


async def test_import_non_duplicate(
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    robot_automation_on_specific_enhancement: uuid.UUID,
):
    """Test importing a non-duplicate reference."""
    references = ReferenceFactory.build_batch(2)
    # Import sequentially to be absolutely sure they're tested against each other.
    reference_ids = {
        (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [reference],
                get_import_file_signed_url=get_import_file_signed_url,
            )
        ).pop()
        for reference in references
    }

    for reference_id in reference_ids:
        duplicate_decision = await poll_duplicate_process(pg_session, reference_id)
        assert duplicate_decision["duplicate_determination"] in (
            DuplicateDetermination.CANONICAL,
            DuplicateDetermination.UNSEARCHABLE,
        )
        assert duplicate_decision["canonical_reference_id"] is None

        with pytest.raises(TestPollingExhaustedError):
            await poll_pending_enhancement(
                pg_session,
                reference_id=reference_id,
                robot_id=robot_automation_on_specific_enhancement,
            )

    # Check that the Elasticsearch index contains the reference as-is.
    es_result = await es_client.search(
        index=ReferenceDocument.Index.name,
        query={"match_all": {}},
    )
    assert es_result["hits"]["total"]["value"] == 2
    assert {hit["_id"] for hit in es_result["hits"]["hits"]} == {
        str(reference_id) for reference_id in reference_ids
    }
    references = [hit["_source"] for hit in es_result["hits"]["hits"]]
    assert {reference["duplicate_determination"] for reference in references} <= {
        "canonical",
        "unsearchable",
    }


async def test_canonical_becomes_duplicate(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    duplicate_reference: Reference,
):
    """Verify behaviour when a canonical-like reference becomes a duplicate."""
    canonical_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()

    # Manually insert the duplicate reference to avoid side effects
    pg_session.add(SQLReference.from_domain(duplicate_reference))
    pg_session.add(
        SQLReferenceDuplicateDecision(
            id=(canonical_decision_id := uuid.uuid4()),
            reference_id=duplicate_reference.id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
            active_decision=True,
            candidate_canonical_ids=[],
        )
    )
    await pg_session.commit()

    # Index it to elasticsearch
    await destiny_client_v1.post(
        f"/system/indices/{ReferenceDocument.Index.name}/repair/"
    )
    for retry in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(1)):
        with retry:
            await refresh_reference_index(es_client)
            es_result = await es_client.search(
                index=ReferenceDocument.Index.name,
                query={"match_all": {}},
            )
            assert es_result["hits"]["total"]["value"] == 2
            assert {hit["_id"] for hit in es_result["hits"]["hits"]} == {
                str(canonical_reference_id),
                str(duplicate_reference.id),
            }

    # Now deduplicate the duplicate again and check downstream
    await destiny_client_v1.post(
        "/references/duplicate-decisions/",
        json={
            "reference_ids": [str(duplicate_reference.id)],
        },
    )

    # Check the decisions
    duplicate_decision = await poll_duplicate_process(
        pg_session,
        duplicate_reference.id,
        required_state=DuplicateDetermination.DUPLICATE,
    )
    assert (
        duplicate_decision["duplicate_determination"]
        == DuplicateDetermination.DUPLICATE
    )
    assert duplicate_decision["canonical_reference_id"] == canonical_reference_id
    old_decision = await pg_session.get(
        SQLReferenceDuplicateDecision, canonical_decision_id
    )
    assert old_decision
    assert not old_decision.active_decision

    # Check that the Elasticsearch index contains only the canonical.
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)
    es_result = await es_client.search(
        index=ReferenceDocument.Index.name,
        query={
            "terms": {
                "_id": [
                    str(canonical_reference_id),
                    str(duplicate_reference.id),
                ]
            }
        },
    )
    assert es_result["hits"]["total"]["value"] == 1
    assert es_result["hits"]["hits"][0]["_id"] == str(canonical_reference_id)
    es_source = es_result["hits"]["hits"][0]["_source"]
    assert es_source["duplicate_determination"] == DuplicateDetermination.CANONICAL
