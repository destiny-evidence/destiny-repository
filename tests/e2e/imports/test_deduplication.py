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

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    PendingEnhancementStatus,
    Reference,
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
    import_references,
    poll_duplicate_process,
    poll_pending_enhancement,
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


async def test_import_duplicates(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    automation_triggering_annotation_enhancement: Enhancement,
    robot_automation_on_specific_enhancement: uuid.UUID,
):
    """Test importing a duplicate reference."""
    canonical_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()

    # First, an exact duplicate. Check that the decision is correct and that the
    # reference is not imported.
    exact_duplicate_reference = canonical_reference.model_copy(deep=True)
    # Make it a subsetting reference
    assert exact_duplicate_reference.enhancements
    exact_duplicate_reference.enhancements.pop()
    exact_duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
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

    # Now, a near duplicate. Modify it a small amount and check the decision is correct
    # and that the reference is imported.
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
    duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            [duplicate],
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
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)
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
