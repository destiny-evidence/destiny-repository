"""End-to-end tests for import deduplication."""

import asyncio
import json
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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import Retrying, stop_after_attempt, wait_fixed

from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    ExternalIdentifierType,
    PendingEnhancementStatus,
    Reference,
    Visibility,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.models.sql import (
    ReferenceDuplicateDecision as SQLReferenceDuplicateDecision,
)
from app.domain.robots.models.models import Robot
from tests.e2e.utils import (
    TestPollingExhaustedError,
    import_references,
    poll_duplicate_process,
    poll_pending_enhancement,
    refresh_reference_index,
    refresh_robot_automation_index,
)
from tests.factories import (
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    BooleanAnnotationFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    OpenAlexIdentifierFactory,
    ReferenceFactory,
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
    """
    Get a pre-defined annotation that will be used to trigger a robot automation.

    See robot_automation_on_specific_enhancement below for the corresponding robot automation.
    """
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
            # Another annotation enhancement for fun
            EnhancementFactory.build(content=AnnotationEnhancementFactory.build()),
        ],
        identifiers=[
            # Make sure we have at least one non-other identifier
            LinkedExternalIdentifierFactory.build(
                identifier=DOIIdentifierFactory.build()
            ),
            LinkedExternalIdentifierFactory.build(),
        ],
        visibility=Visibility.PUBLIC,
    )


@pytest.fixture
def duplicate_reference(
    canonical_reference: Reference,
    automation_triggering_annotation_enhancement: Enhancement,
) -> Reference:
    """Get a slightly mutated canonical reference to be a duplicate."""
    duplicate = canonical_reference.model_copy(deep=True, update={"id": uuid.uuid4()})
    assert duplicate.enhancements
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


@pytest.fixture
def non_duplicate_reference(
    canonical_reference: Reference,
) -> Reference:
    """Get a slightly mutated canonical reference to definitely not be a duplicate."""
    duplicate = canonical_reference.model_copy(deep=True, update={"id": uuid.uuid4()})
    assert duplicate.enhancements
    assert isinstance(
        duplicate.enhancements[0].content, BibliographicMetadataEnhancement
    )
    assert duplicate.enhancements[0].content.publication_year
    duplicate.enhancements[0].content.publication_year -= 10
    return duplicate


@pytest.fixture
def exact_duplicate_reference(canonical_reference: Reference) -> Reference:
    """Get a reference that is a subset of the canonical."""
    exact_duplicate_reference = canonical_reference.model_copy(
        deep=True, update={"id": uuid.uuid4()}
    )
    assert exact_duplicate_reference.enhancements

    # Remove one enhancement to make it an exact subset
    exact_duplicate_reference.enhancements.pop()

    # Check we have a bibliography and a raw enhanceement
    assert isinstance(
        exact_duplicate_reference.enhancements[0].content,
        BibliographicMetadataEnhancement,
    )

    return exact_duplicate_reference


# ruff: noqa: E501
@pytest.fixture
async def robot_automation_on_specific_enhancement(
    destiny_client_v1: httpx.AsyncClient,
    es_client: AsyncElasticsearch,
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
    await refresh_robot_automation_index(es_client)
    return robot.id


async def test_import_exact_duplicate(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    exact_duplicate_reference: Reference,
):
    """Test importing an exact duplicate reference."""
    await import_references(
        destiny_client_v1,
        pg_session,
        es_client,
        [canonical_reference],
        get_import_file_signed_url,
    )
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)

    exact_duplicate_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [exact_duplicate_reference],
            get_import_file_signed_url,
        )
    ).pop()
    await poll_duplicate_process(
        pg_session, exact_duplicate_reference_id, DuplicateDetermination.EXACT_DUPLICATE
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
    await es_client.indices.refresh(index=ReferenceDocument.Index.name)

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
        pg_session, duplicate_reference_id, DuplicateDetermination.DUPLICATE
    )
    assert duplicate_decision.canonical_reference_id == canonical_reference_id

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


async def test_import_non_duplicate(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    robot_automation_on_specific_enhancement: uuid.UUID,
    canonical_reference: Reference,
    non_duplicate_reference: Reference,
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
        for reference in [canonical_reference, non_duplicate_reference]
    }

    for reference_id in reference_ids:
        duplicate_decision = await poll_duplicate_process(
            pg_session, reference_id, DuplicateDetermination.CANONICAL
        )
        assert duplicate_decision.canonical_reference_id is None

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


# NB tests below this line are probably best placed in `enhancements.test_deduplication.py`,
# with new enhancements triggering the changes, but at time of writing the enhancement->dedup
# trigger is not yet implemented.
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
        duplicate_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
    )
    assert duplicate_decision.canonical_reference_id == canonical_reference_id
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


async def test_duplicate_becomes_canonical(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    non_duplicate_reference: Reference,
):
    """Verify behaviour when a duplicate reference becomes canonical."""
    # First import the canonical and duplicate references
    canonical_reference_id = (
        await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [canonical_reference],
            get_import_file_signed_url,
        )
    ).pop()

    # Directly import the non-duplicate reference to avoid side effects
    pg_session.add(SQLReference.from_domain(non_duplicate_reference))
    pg_session.add(
        SQLReferenceDuplicateDecision(
            id=(non_canonical_decision_id := uuid.uuid4()),
            reference_id=non_duplicate_reference.id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=canonical_reference_id,
            active_decision=True,
            candidate_canonical_ids=[canonical_reference_id],
        )
    )
    await pg_session.commit()

    # Now deduplicate the non-duplicate again and check downstream
    await destiny_client_v1.post(
        "/references/duplicate-decisions/",
        json={
            "reference_ids": [str(non_duplicate_reference.id)],
        },
    )

    # Check the decisions
    duplicate_decision = await poll_duplicate_process(
        pg_session,
        non_duplicate_reference.id,
        required_state=DuplicateDetermination.DECOUPLED,
    )
    assert (
        duplicate_decision.duplicate_determination == DuplicateDetermination.DECOUPLED
    )
    assert duplicate_decision.detail
    assert "Existing duplicate decision changed" in duplicate_decision.detail
    assert not duplicate_decision.canonical_reference_id
    assert not duplicate_decision.active_decision

    old_decision = await pg_session.get(
        SQLReferenceDuplicateDecision, non_canonical_decision_id
    )
    assert old_decision
    assert old_decision.active_decision


async def test_duplicate_change(  # noqa: PLR0913
    destiny_client_v1: httpx.AsyncClient,
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    duplicate_reference: Reference,
    non_duplicate_reference: Reference,
):
    """
    Verify behaviour when a duplicate-like reference becomes a different duplicate.

    We point duplicate->non_duplicate, then the process changes it to duplicate->canonical.
    """
    # First import the canonical and non-duplicate references. Both will register as canonical.
    canonical_reference_id, non_duplicate_reference_id = [
        (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [reference],
                get_import_file_signed_url,
            )
        ).pop()
        for reference in (canonical_reference, non_duplicate_reference)
    ]

    # Now manually import the duplicate reference to avoid side effects
    # Manually insert the duplicate reference to avoid side effects
    pg_session.add(SQLReference.from_domain(duplicate_reference))
    pg_session.add(
        SQLReferenceDuplicateDecision(
            id=(duplicate_decision_id := uuid.uuid4()),
            reference_id=duplicate_reference.id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            active_decision=True,
            candidate_canonical_ids=[],
            canonical_reference_id=non_duplicate_reference_id,
        )
    )
    await pg_session.commit()

    # Deduplicate the duplicate again and check downstream
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
        required_state=DuplicateDetermination.DECOUPLED,
    )
    assert duplicate_decision.detail
    assert "Existing duplicate decision changed" in duplicate_decision.detail
    assert duplicate_decision.canonical_reference_id == canonical_reference_id
    assert not duplicate_decision.active_decision

    old_decision = await pg_session.get(
        SQLReferenceDuplicateDecision, duplicate_decision_id
    )
    assert old_decision
    assert old_decision.active_decision


async def test_deduplication_shortcut(  # noqa: PLR0913
    configured_repository_factory: Callable[
        [dict], _AsyncGeneratorContextManager[httpx.AsyncClient]
    ],
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    duplicate_reference: Reference,
    robot_automation_on_specific_enhancement: uuid.UUID,
):
    """Test that deduplication shortcutting works as expected."""
    trusted_identifier = LinkedExternalIdentifierFactory.build(
        identifier=OpenAlexIdentifierFactory.build(),
    )
    assert canonical_reference.identifiers
    assert duplicate_reference.identifiers
    canonical_reference.identifiers.append(trusted_identifier)
    duplicate_reference.identifiers.append(trusted_identifier)
    other_reference = canonical_reference.model_copy(
        deep=True, update={"visibility": Visibility.HIDDEN}
    )
    async with configured_repository_factory(
        {
            "TRUSTED_UNIQUE_IDENTIFIER_TYPES": json.dumps(
                [ExternalIdentifierType.OPEN_ALEX.value]
            )
        }
    ) as destiny_client_v1:
        canonical_reference_id = (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [canonical_reference],
                get_import_file_signed_url,
            )
        ).pop()
        other_reference_id = (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [other_reference],
                get_import_file_signed_url,
            )
        ).pop()
        await es_client.indices.refresh(index=ReferenceDocument.Index.name)

        # Delete the existing decision (as if it was never deduplicated)
        await pg_session.execute(
            delete(SQLReferenceDuplicateDecision).where(
                SQLReferenceDuplicateDecision.reference_id == other_reference_id
            )
        )
        await pg_session.commit()

        duplicate_reference_id = (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [duplicate_reference],
                get_import_file_signed_url,
            )
        ).pop()
        decision = await poll_duplicate_process(
            pg_session, duplicate_reference_id, DuplicateDetermination.DUPLICATE
        )
        assert decision.detail == "Shortcutted with trusted identifier(s)"
        assert decision.canonical_reference_id == canonical_reference_id

        # Check that the other reference received the same treatment
        decision = await poll_duplicate_process(
            pg_session, other_reference_id, DuplicateDetermination.DUPLICATE
        )
        assert decision.canonical_reference_id == canonical_reference_id
        assert (
            decision.detail
            == f"Shortcutted via proxy reference {duplicate_reference_id} with trusted identifier(s)"
        )

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


async def test_deduplication_shortcut_from_scratch(  # noqa: PLR0913
    configured_repository_factory: Callable[
        [dict], _AsyncGeneratorContextManager[httpx.AsyncClient]
    ],
    pg_session: AsyncSession,
    es_client: AsyncElasticsearch,
    get_import_file_signed_url: Callable[
        [list[ReferenceFileInput]], _AsyncGeneratorContextManager[str]
    ],
    canonical_reference: Reference,
    duplicate_reference: Reference,
):
    """
    Test that deduplication shortcutting builds a tree as expected.

    In this case, two existing undeduplicated references share different
    unique identifiers with the incoming reference. The incoming reference
    should become the canonical of the two undeduplicated references.
    """
    trusted_identifier_1 = LinkedExternalIdentifierFactory.build(
        identifier=OpenAlexIdentifierFactory.build(),
    )
    trusted_identifier_2 = LinkedExternalIdentifierFactory.build(
        identifier=DOIIdentifierFactory.build(),
    )
    existing_reference_1 = canonical_reference
    existing_reference_2 = canonical_reference.model_copy(deep=True)
    incoming_reference = duplicate_reference
    assert existing_reference_1.identifiers
    assert existing_reference_2.identifiers
    assert incoming_reference.identifiers
    existing_reference_1.identifiers.append(trusted_identifier_1)
    existing_reference_2.identifiers.append(trusted_identifier_2)
    incoming_reference.identifiers.extend([trusted_identifier_1, trusted_identifier_2])

    async with configured_repository_factory(
        {
            "TRUSTED_UNIQUE_IDENTIFIER_TYPES": json.dumps(
                [
                    ExternalIdentifierType.OPEN_ALEX.value,
                    ExternalIdentifierType.DOI.value,
                ]
            ),
        }
    ) as destiny_client_v1:
        existing_reference_ids = await import_references(
            destiny_client_v1,
            pg_session,
            es_client,
            [existing_reference_1, existing_reference_2],
            get_import_file_signed_url,
        )
        await es_client.indices.refresh(index=ReferenceDocument.Index.name)

        # Delete the existing decisions (as if they were never deduplicated)
        await pg_session.execute(
            delete(SQLReferenceDuplicateDecision).where(
                SQLReferenceDuplicateDecision.reference_id.in_(existing_reference_ids)
            )
        )
        await pg_session.commit()

        # Small sleep to ensure that the above transaction is fully settled before proceeding
        # Without this, the below deduplication can deadlock
        # We should find a better way to do this in the future
        await asyncio.sleep(10)

        incoming_reference_id = (
            await import_references(
                destiny_client_v1,
                pg_session,
                es_client,
                [incoming_reference],
                get_import_file_signed_url,
            )
        ).pop()
        decision = await poll_duplicate_process(
            pg_session, incoming_reference_id, DuplicateDetermination.CANONICAL
        )
        assert decision.detail == "Shortcutted with trusted identifier(s)"
        assert not decision.canonical_reference_id

        for existing_reference_id in existing_reference_ids:
            decision = await poll_duplicate_process(
                pg_session, existing_reference_id, DuplicateDetermination.DUPLICATE
            )
            assert decision.canonical_reference_id == incoming_reference_id
            assert (
                decision.detail
                == f"Shortcutted via proxy reference {incoming_reference_id} with trusted identifier(s)"
            )

        # Check that the Elasticsearch index contains only the canonical, with the two duplicates
        # removed
        es_result = await es_client.search(
            index=ReferenceDocument.Index.name,
            query={
                "terms": {
                    "_id": [
                        str(incoming_reference_id),
                        *[str(_id) for _id in existing_reference_ids],
                    ]
                }
            },
        )
        assert es_result["hits"]["total"]["value"] == 1
        assert es_result["hits"]["hits"][0]["_id"] == str(incoming_reference_id)
        es_source = es_result["hits"]["hits"][0]["_source"]
        assert es_source["duplicate_determination"] == "canonical"
