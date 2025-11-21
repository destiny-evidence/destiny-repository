"""Intergration test for deduplication imports."""

import uuid

import pytest
from destiny_sdk.enhancements import (
    Authorship,
    BibliographicMetadataEnhancement,
    EnhancementFileInput,
    RawEnhancement,
)
from destiny_sdk.references import ReferenceFileInput
from elasticsearch import AsyncElasticsearch
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    Reference,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from tests.factories import (
    AnnotationEnhancementFactory,
    BibliographicMetadataEnhancementFactory,
    DOIIdentifierFactory,
    EnhancementFactory,
    LinkedExternalIdentifierFactory,
    RawEnhancementFactory,
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
def canonical_reference(canonical_bibliographic_enhancement: Enhancement) -> Reference:
    """Get a pre-defined canonical reference."""
    return ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(content=canonical_bibliographic_enhancement),
            # And a raw enhancement because these could cause problems
            EnhancementFactory.build(content=RawEnhancementFactory.build()),
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
    )


def reference_as_file_input(reference: Reference):
    """Turn a reference into a file input."""
    return ReferenceFileInput(
        visibility=reference.visibility,
        enhancements=[
            EnhancementFileInput(**e.model_dump()) for e in reference.enhancements or []
        ],
        identifiers=[i.identifier for i in reference.identifiers or []],
    )


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

    assert isinstance(exact_duplicate_reference.enhancements[1].content, RawEnhancement)

    return exact_duplicate_reference


async def test_ingest_exact_duplicate(
    session: AsyncSession,
    es_client: AsyncElasticsearch,
    canonical_reference: Reference,
    exact_duplicate_reference: Reference,
):
    """Test the full ingestion and deduplication of an exact duplicate."""
    service = ReferenceService(
        anti_corruption_service=ReferenceAntiCorruptionService(
            blob_repository=BlobRepository()
        ),
        sql_uow=AsyncSqlUnitOfWork(session=session),
        es_uow=AsyncESUnitOfWork(client=es_client),
    )

    reference_create_result = await service.ingest_reference(
        record_str=reference_as_file_input(canonical_reference).model_dump_json(),
        entry_ref=0,
    )

    assert reference_create_result.reference_id
    assert not reference_create_result.errors
    assert reference_create_result.duplicate_decision_id

    reference_duplicate_decision = await service.get_reference_duplicate_decision(
        reference_create_result.duplicate_decision_id
    )

    assert (
        reference_duplicate_decision.duplicate_determination
        == DuplicateDetermination.PENDING
    )

    (
        reference_duplicate_decision,
        _,
    ) = await service.process_reference_duplicate_decision(reference_duplicate_decision)

    # Assert that this would be marked Canonical if processed
    assert (
        reference_duplicate_decision.duplicate_determination
        == DuplicateDetermination.CANONICAL
    )

    duplicate_reference_create_result = await service.ingest_reference(
        record_str=reference_as_file_input(exact_duplicate_reference).model_dump_json(),
        entry_ref=0,
    )

    assert reference_create_result.reference_id
    assert not reference_create_result.errors
    assert duplicate_reference_create_result.duplicate_decision_id

    duplicate_reference_duplicate_decision = (
        await service.get_reference_duplicate_decision(
            duplicate_reference_create_result.duplicate_decision_id
        )
    )

    assert (
        duplicate_reference_duplicate_decision.duplicate_determination
        == DuplicateDetermination.EXACT_DUPLICATE
    )
