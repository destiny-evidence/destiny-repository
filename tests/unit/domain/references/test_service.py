"""Unit tests for the ReferenceService class."""

import datetime
import json
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid7

import pytest
from destiny_sdk.enhancements import BibliographicMetadataEnhancement
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import ReferenceFileInput

from app.core.exceptions import (
    DuplicateEnhancementError,
    InvalidParentEnhancementError,
    SQLNotFoundError,
)
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierAdapter,
    LinkedExternalIdentifier,
    PendingEnhancement,
    PendingEnhancementStatus,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceWithChangeset,
    RobotAutomationPercolationResult,
    RobotEnhancementBatch,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.robots.models.models import Robot
from app.persistence.blob.models import BlobStorageFile
from app.utils.time_and_date import utc_now


@pytest.fixture
def test_robot():
    return Robot(
        description="fake robot for unit test",
        name="Test Robot",
        owner="test",
    )


@pytest.mark.asyncio
async def test_get_reference_happy_path(fake_repository, fake_uow):
    dummy_id = uuid7()
    dummy_reference = Reference(id=dummy_id)
    repo = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    dummy_id = uuid7()
    with pytest.raises(SQLNotFoundError):
        await service.get_reference(dummy_id)


@pytest.mark.asyncio
async def test_add_identifier_happy_path(fake_repository, fake_uow):
    dummy_id = uuid7()
    dummy_reference = Reference(id=dummy_id)
    repo_refs = fake_repository(init_entries=[dummy_reference])
    repo_ids = fake_repository()
    uow = fake_uow(references=repo_refs, external_identifiers=repo_ids)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    identifier_data = {"identifier": "W1234", "identifier_type": "open_alex"}
    fake_identifier_create = ExternalIdentifierAdapter.validate_python(identifier_data)
    returned_identifier = await service.add_identifier(dummy_id, fake_identifier_create)
    assert getattr(returned_identifier, "reference_id", None) == dummy_id
    for k, v in identifier_data.items():
        assert getattr(returned_identifier.identifier, k, None) == v


@pytest.mark.asyncio
async def test_add_identifier_reference_not_found(fake_repository, fake_uow):
    repo_refs = fake_repository()
    repo_ids = fake_repository()
    uow = fake_uow(references=repo_refs, external_identifiers=repo_ids)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    dummy_id = uuid7()
    fake_identifier_create = ExternalIdentifierAdapter.validate_python(
        {"identifier": "W1234", "identifier_type": "open_alex"}
    )
    with pytest.raises(SQLNotFoundError):
        await service.add_identifier(dummy_id, fake_identifier_create)


@pytest.mark.asyncio
async def test_add_enhancement_happy_path(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid7())
    repo_refs = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo_refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id, **fake_enhancement_data
    )

    await service.add_enhancement(enhancement_to_add)

    reference_enhancements = repo_refs.get_first_record().enhancements

    assert len(reference_enhancements) == 1
    assert reference_enhancements[0].id == enhancement_to_add.id


@pytest.mark.asyncio
async def test_add_enhancement_reference_does_not_exist(
    fake_repository, fake_uow, fake_enhancement_data
):
    uow = fake_uow(references=fake_repository())
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=uuid7(),  # Doesn't exist
        **fake_enhancement_data,
    )

    with pytest.raises(SQLNotFoundError):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_add_enhancement_derived_from_does_not_exist(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid7())
    repo_refs = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo_refs, enhancements=fake_repository())
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id,
        derived_from=[uuid7()],
        **fake_enhancement_data,
    )

    with pytest.raises(InvalidParentEnhancementError):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_add_enhancement_derived_from_enhancement_for_different_reference(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid7())
    repo_refs = fake_repository(init_entries=[dummy_reference])

    dummy_parent_enhancement = Enhancement(
        reference_id=uuid7(),  # Not the reference we'll enhance
        **fake_enhancement_data,
    )

    repo_enhs = fake_repository(init_entries=[dummy_parent_enhancement])
    uow = fake_uow(references=repo_refs, enhancements=repo_enhs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id,  # different reference id
        derived_from=[dummy_parent_enhancement.id],
        **fake_enhancement_data,
    )

    with pytest.raises(InvalidParentEnhancementError, match="same reference tree"):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_add_enhancement_derived_from_enhancement_for_duplicate_reference(
    fake_repository, fake_uow, fake_enhancement_data
):
    dup_ref_id = uuid7()
    dummy_reference = Reference(
        id=uuid7(), duplicate_references=[Reference(id=dup_ref_id)]
    )
    repo_refs = fake_repository(init_entries=[dummy_reference])

    dummy_parent_enhancement = Enhancement(
        reference_id=dup_ref_id,  # Derived from an enhancement from a duplicate ref
        **fake_enhancement_data,
    )

    repo_enhs = fake_repository(init_entries=[dummy_parent_enhancement])
    uow = fake_uow(references=repo_refs, enhancements=repo_enhs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id,  # different reference id
        derived_from=[dummy_parent_enhancement.id],
        **fake_enhancement_data,
    )

    reference = await service.add_enhancement(enhancement_to_add)
    assert reference.enhancements[0].id == enhancement_to_add.id


@pytest.mark.asyncio
async def test_add_enhancement_duplicate_enhancement(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid7())
    repo_refs = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo_refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id, **fake_enhancement_data
    )

    # First addition should succeed
    await service.add_enhancement(enhancement_to_add)

    # Second addition with the same data should raise DuplicateEnhancementError
    with pytest.raises(DuplicateEnhancementError):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_register_reference_enhancement_request(fake_repository, fake_uow):
    """
    Test the happy path for registering an enhancement request.
    """
    reference_ids = [uuid7(), uuid7()]
    robot_id = uuid7()
    request_id = uuid7()
    enhancement_request = EnhancementRequest(
        id=request_id,
        reference_ids=reference_ids,
        robot_id=robot_id,
        enhancement_parameters={"param": "value"},
    )

    fake_requests = fake_repository()
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )
    fake_pending_enhancements = fake_repository()

    uow = fake_uow(
        enhancement_requests=fake_requests,
        references=fake_references,
        pending_enhancements=fake_pending_enhancements,
    )
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    created_request = await service.register_reference_enhancement_request(
        enhancement_request=enhancement_request
    )

    stored_request = fake_requests.get_first_record()

    assert created_request == stored_request
    assert created_request.reference_ids == reference_ids
    assert created_request.enhancement_parameters == {"param": "value"}

    pending_enhancements_records = await fake_pending_enhancements.get_all()
    assert len(pending_enhancements_records) == len(reference_ids)
    for pending_enhancement in pending_enhancements_records:
        assert pending_enhancement.robot_id == robot_id
        assert pending_enhancement.enhancement_request_id == request_id
        assert pending_enhancement.reference_id in reference_ids


@pytest.mark.asyncio
async def test_register_reference_enhancement_request_missing_pk(
    fake_repository, fake_uow
):
    """
    Test registering an enhancement request with a missing reference ID.
    """
    reference_ids = [uuid7(), uuid7()]
    missing_reference_id = uuid7()
    robot_id = uuid7()
    enhancement_request = EnhancementRequest(
        id=uuid7(),
        reference_ids=[*reference_ids, missing_reference_id],
        robot_id=robot_id,
        enhancement_parameters={"param": "value"},
    )

    fake_requests = fake_repository()
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )

    uow = fake_uow(
        enhancement_requests=fake_requests,
        references=fake_references,
    )
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    with pytest.raises(
        SQLNotFoundError, match=f"{{'{missing_reference_id}'}} not in repository"
    ):
        await service.register_reference_enhancement_request(
            enhancement_request=enhancement_request
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("find_exact_duplicate_return", "should_merge", "expected_decision_id"),
    [
        (None, True, "decision-id"),
        (Mock(id="reference-id"), False, None),
    ],
)
async def test_ingest_reference(
    fake_repository,
    fake_uow,
    find_exact_duplicate_return,
    should_merge,
    expected_decision_id,
):
    """Test ingestion pathing."""

    repo = fake_repository()
    uow = fake_uow(references=repo)
    es_uow = fake_uow()
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, es_uow
    )

    dummy_decision = Mock()
    dummy_decision.id = "decision-id"

    # Create a minimal valid ReferenceFileInput instance
    dummy_reference_input = ReferenceFileInput(
        visibility="public",
        identifiers=[{"identifier": "W1234", "identifier_type": "open_alex"}],
        enhancements=[],
    )
    dummy_parsed = ReferenceCreateResult(reference=dummy_reference_input)

    mock_reference = Mock(id="reference-id")

    # Patch deduplication service methods
    with (
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "register_duplicate_decision_for_reference",
            AsyncMock(return_value=dummy_decision),
        ) as mock_register,
        patch.object(service, "_merge_reference", AsyncMock()) as mock_merge,
        patch.object(
            service._anti_corruption_service,  # noqa: SLF001
            "reference_from_sdk_file_input",
            Mock(return_value=mock_reference),
        ),
        patch.object(
            ReferenceCreateResult, "from_raw", Mock(return_value=dummy_parsed)
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "find_exact_duplicate",
            AsyncMock(return_value=find_exact_duplicate_return),
        ) as mock_find,
    ):
        result = await service.ingest_reference("{}", 1)
        mock_find.assert_awaited_once()
        mock_register.assert_awaited_once()
        if should_merge:
            mock_merge.assert_awaited_once_with(mock_reference)
        else:
            mock_merge.assert_not_awaited()
        assert getattr(result, "duplicate_decision_id", None) == expected_decision_id


@pytest.mark.asyncio
async def test_detect_robot_automations(
    fake_repository, fake_uow, fake_enhancement_data
):
    """Test the detection of robot automations for references."""
    reference_id = uuid7()
    robot_id = uuid7()

    enhancement = Enhancement(reference_id=reference_id, **fake_enhancement_data)
    reference = Reference(
        id=reference_id,
        visibility="public",
        enhancements=[enhancement],
        duplicate_references=[],
    )
    reference_2 = Reference(
        id=uuid7(),
        visibility="public",
        enhancements=[enhancement],
    )

    # Extend the fake repository with get_hydrated and percolation
    class FakeRepo(fake_repository):
        def __init__(self, init_entries=None):
            super().__init__(init_entries=init_entries)
            self.hydrated_references = init_entries

        async def percolate(self, documents):
            # Returns a match on all documents against one robot
            return [
                RobotAutomationPercolationResult(
                    robot_id=robot_id,
                    reference_ids={
                        getattr(document, "reference_id", getattr(document, "id", None))
                        for document in documents
                    },
                )
            ]

    fake_enhancements_repo = fake_repository([enhancement])
    fake_references_repo = FakeRepo([reference, reference_2])
    fake_robot_automations_repo = FakeRepo()

    sql_uow = fake_uow(
        references=fake_references_repo,
        enhancements=fake_enhancements_repo,
    )
    es_uow = fake_uow(robot_automations=fake_robot_automations_repo)

    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository), sql_uow=sql_uow, es_uow=es_uow
    )
    results = await service.detect_robot_automations(
        reference=ReferenceWithChangeset(
            **reference_2.model_dump(), changeset=reference_2
        ),
        enhancement_ids=[enhancement.id],
    )
    assert len(results) == 1
    assert results[0].robot_id == robot_id
    assert len(results[0].reference_ids) == 2


@pytest.fixture
def canonical_reference():
    canonical_id = uuid7()
    content = BibliographicMetadataEnhancement(
        title="Test Title",
        authorship=[],
        publication_year=2024,
        publication_date=None,
    )
    enhancement = Enhancement(
        id=uuid7(),
        reference_id=canonical_id,
        source="unit-test",
        visibility="public",
        robot_version=None,
        derived_from=None,
        content=content,
    )
    return Reference(
        id=canonical_id,
        visibility="public",
        enhancements=[enhancement],
        identifiers=[],
        duplicate_decision=ReferenceDuplicateDecision(
            reference_id=canonical_id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
        ),
        duplicate_references=[],
    )


@pytest.fixture
def get_duplicate_reference():
    def _make(canonical_id):
        duplicate_id = uuid7()
        return Reference(
            id=duplicate_id,
            visibility="public",
            enhancements=[],
            identifiers=[
                LinkedExternalIdentifier(
                    reference_id=duplicate_id,
                    identifier=DOIIdentifier(
                        identifier="10.1234/example.doi",
                    ),
                )
            ],
            duplicate_decision=ReferenceDuplicateDecision(
                reference_id=duplicate_id,
                duplicate_determination=DuplicateDetermination.DUPLICATE,
                canonical_reference_id=canonical_id,
            ),
            duplicate_references=[],
        )

    return _make


@pytest.mark.asyncio
async def test_get_deduplicated_canonical_reference(
    fake_repository, fake_uow, canonical_reference
):
    refs = fake_repository([canonical_reference])
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical = await service._get_deduplicated_canonical_reference(  # noqa: SLF001
        canonical_reference.id
    )
    assert canonical.id == canonical_reference.id
    assert len(canonical.enhancements) == 1
    assert len(canonical.identifiers) == 0


@pytest.mark.asyncio
async def test_get_deduplicated_canonical_reference_with_duplicates(
    fake_repository, fake_uow, canonical_reference, get_duplicate_reference
):
    duplicate_reference = get_duplicate_reference(canonical_reference.id)
    canonical_reference.duplicate_references = [duplicate_reference]
    refs = fake_repository([canonical_reference, duplicate_reference])
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical = await service._get_deduplicated_canonical_reference(  # noqa: SLF001
        canonical_reference.id
    )
    assert canonical.id == canonical_reference.id
    assert len(canonical.enhancements) == 1
    assert len(canonical.identifiers) == 1


@pytest.mark.asyncio
async def test_get_deduplicated_reference_duplicate_to_canonical(
    fake_repository, fake_uow, canonical_reference, get_duplicate_reference
):
    duplicate_reference = get_duplicate_reference(canonical_reference.id)
    canonical_reference.duplicate_references = [duplicate_reference]
    refs = fake_repository([canonical_reference, duplicate_reference])
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical = await service._get_deduplicated_canonical_reference(  # noqa: SLF001
        duplicate_reference.id
    )
    assert canonical.id == canonical_reference.id
    assert len(canonical.enhancements) == 1
    assert len(canonical.identifiers) == 1

    duplicate = await service._get_deduplicated_reference(  # noqa: SLF001
        duplicate_reference.id
    )
    assert duplicate.id == duplicate_reference.id
    assert len(duplicate.enhancements) == 0
    assert len(duplicate.identifiers) == 1


@pytest.mark.asyncio
async def test_get_deduplicated_canonical_reference_duplicate_chain(
    fake_repository, fake_uow, canonical_reference, get_duplicate_reference
):
    intermediate_reference = get_duplicate_reference(canonical_reference.id)
    duplicate_reference = get_duplicate_reference(intermediate_reference.id)
    canonical_reference.duplicate_references = [intermediate_reference]
    intermediate_reference.duplicate_references = [duplicate_reference]
    refs = fake_repository(
        [canonical_reference, intermediate_reference, duplicate_reference]
    )
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical = await service._get_deduplicated_canonical_reference(  # noqa: SLF001
        duplicate_reference.id
    )
    assert canonical.id == canonical_reference.id
    assert len(canonical.enhancements) == 1
    assert len(canonical.identifiers) == 2

    canonical = await service._get_deduplicated_canonical_reference(  # noqa: SLF001
        intermediate_reference.id
    )
    assert canonical.id == canonical_reference.id
    assert len(canonical.enhancements) == 1
    assert len(canonical.identifiers) == 2


async def test_get_deduplicated_canonical_references(
    fake_repository, fake_uow, canonical_reference, get_duplicate_reference
):
    duplicate_reference = get_duplicate_reference(canonical_reference.id)
    canonical_reference.duplicate_references = [duplicate_reference]
    refs = fake_repository([canonical_reference, duplicate_reference])
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical_list = await service._get_deduplicated_canonical_references(  # noqa: SLF001
        reference_ids=[canonical_reference.id, duplicate_reference.id]
    )
    assert len(canonical_list) == 2
    assert canonical_list[0] == canonical_list[1]

    # Check it works when passing in references directly too
    assert canonical_list == await service._get_deduplicated_canonical_references(  # noqa: SLF001
        references=[canonical_reference, duplicate_reference]
    )


async def test_get_canonical_reference_with_implied_changeset(
    fake_uow, fake_repository
):
    """Test getting canonical reference and implied changeset."""
    duplicate_id = uuid7()
    canonical_id = uuid7()
    duplicate_reference = Reference(
        id=duplicate_id,
        visibility="public",
        duplicate_decision=ReferenceDuplicateDecision(
            reference_id=duplicate_id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=canonical_id,
        ),
        duplicate_references=[],
    )
    canonical_reference = Reference(
        id=canonical_id,
        visibility="public",
        duplicate_decision=ReferenceDuplicateDecision(
            reference_id=duplicate_id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
        ),
        duplicate_references=[duplicate_reference],
    )
    refs = fake_repository([canonical_reference, duplicate_reference])
    uow = fake_uow(references=refs)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )
    canonical = await service._get_deduplicated_canonical_reference(duplicate_id)  # noqa: SLF001
    result = await service.get_canonical_reference_with_implied_changeset(duplicate_id)
    assert isinstance(result, ReferenceWithChangeset)
    assert result.changeset == duplicate_reference
    assert result.model_dump(exclude={"changeset"}) == canonical.model_dump()


async def test_get_reference_changesets_from_enhancements(fake_uow, fake_repository):
    """Test getting reference changesets from enhancements."""
    reference_1_id, reference_2_id = uuid7(), uuid7()
    enhancement_1 = Enhancement(
        id=uuid7(),
        reference_id=reference_1_id,
        source="unit-test",
        visibility="public",
        robot_version=None,
        derived_from=None,
        content=BibliographicMetadataEnhancement(
            title="Test Title 1",
            authorship=[],
            publication_year=2023,
            publication_date=None,
        ),
    )
    enhancement_2 = Enhancement(
        id=uuid7(),
        reference_id=reference_2_id,
        source="unit-test",
        visibility="public",
        robot_version=None,
        derived_from=None,
        content=BibliographicMetadataEnhancement(
            title="Test Title 2",
            authorship=[],
            publication_year=2024,
            publication_date=None,
        ),
    )
    fake_enhancements_repo = fake_repository([enhancement_1, enhancement_2])
    fake_references_repo = fake_repository(
        [
            Reference(
                id=reference_1_id,
                visibility="public",
                enhancements=[],
                duplicate_references=[],
            ),
            Reference(
                id=reference_2_id,
                visibility="public",
                enhancements=[],
                duplicate_references=[],
            ),
        ]
    )
    sql_uow = fake_uow(
        references=fake_references_repo,
        enhancements=fake_enhancements_repo,
    )
    es_uow = fake_uow()

    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository), sql_uow=sql_uow, es_uow=es_uow
    )
    changesets = await service._get_reference_changesets_from_enhancements(  # noqa: SLF001
        [enhancement_1.id, enhancement_2.id]
    )
    assert len(changesets) == 2
    assert [cs.id for cs in changesets] == [reference_1_id, reference_2_id]
    assert [cs.changeset.enhancements[0].id for cs in changesets] == [
        enhancement_1.id,
        enhancement_2.id,
    ]


@pytest.mark.asyncio
async def test_create_robot_enhancement_batch(fake_repository, fake_uow, test_robot):
    """Test the creation of a robot enhancement batch."""
    mock_blob_repository = AsyncMock()
    mock_blob_repository.upload_file_to_blob_storage.return_value = BlobStorageFile(
        location="minio",
        container="test",
        filename="test.jsonl",
        path="robot_enhancement_batch_reference_data",
    )

    references = [Reference(id=uuid7()) for _ in range(3)]
    pending_enhancements = [
        PendingEnhancement(
            reference_id=ref.id,
            robot_id=test_robot.id,
            enhancement_request_id=uuid7(),
        )
        for ref in references
    ]
    # Add one more pending enhancement on the same reference - see note in service
    # about uniqueness restriction
    pending_enhancements.append(
        PendingEnhancement(
            reference_id=references[0].id,
            robot_id=test_robot.id,
            enhancement_request_id=uuid7(),
        )
    )

    # Create a specialized fake references repository with get_hydrated method
    class FakeReferencesRepository(fake_repository):
        async def get_hydrated(
            self,
            reference_ids: list,
            enhancement_types: list | None = None,
            external_identifier_types: list | None = None,
        ) -> list:
            """Get hydrated references by IDs (simplified for testing)."""
            return await self.get_by_pks(reference_ids)

    uow = fake_uow(
        references=FakeReferencesRepository(init_entries=references),
        pending_enhancements=fake_repository(init_entries=pending_enhancements),
        robot_enhancement_batches=fake_repository(),
    )
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    batch_pending_enhancements = await service.get_pending_enhancements_for_robot(
        robot_id=test_robot.id, limit=10
    )

    assert len(batch_pending_enhancements) == 3

    lease = datetime.timedelta(minutes=5)
    expected_expiry_time = utc_now() + lease

    created_batch = await service.create_robot_enhancement_batch(
        robot_id=test_robot.id,
        pending_enhancements=batch_pending_enhancements,
        lease_duration=lease,
        blob_repository=mock_blob_repository,
    )

    assert isinstance(created_batch, RobotEnhancementBatch)
    assert created_batch.robot_id == test_robot.id

    for pe in pending_enhancements[:3]:
        updated_pe = await uow.pending_enhancements.get_by_pk(pe.id)
        assert updated_pe.status == PendingEnhancementStatus.PROCESSING
        assert updated_pe.robot_enhancement_batch_id == created_batch.id
        assert abs(updated_pe.expires_at - expected_expiry_time) < datetime.timedelta(
            seconds=1
        )

    assert (
        await uow.pending_enhancements.get_by_pk(pending_enhancements[3].id)
    ).status == PendingEnhancementStatus.PENDING

    mock_blob_repository.upload_file_to_blob_storage.assert_awaited_once()

    args, kwargs = mock_blob_repository.upload_file_to_blob_storage.call_args
    filestream = kwargs["content"]
    file_content = await filestream.read()
    content_lines = file_content.getvalue().decode().strip().split("\n")

    # Verify we have the correct number of references and each has the expected ID
    assert len(content_lines) == len(references)
    assert {data["id"] for data in (json.loads(line) for line in content_lines)} == {
        str(ref.id) for ref in references
    }

    assert created_batch.reference_data_file is not None
    assert created_batch.reference_data_file.endswith(".jsonl")


@pytest.mark.asyncio
async def test_renew_robot_enhancement_batch_lease(
    fake_repository, fake_uow, test_robot
):
    """Test renewing the lease of a robot enhancement batch."""
    initial_expiry = utc_now() + datetime.timedelta(minutes=1)
    updated_lease = datetime.timedelta(minutes=5)

    robot_enhancement_batch = RobotEnhancementBatch(
        robot_id=test_robot.id,
        lease_expires_at=initial_expiry,
    )

    repo = fake_repository(init_entries=[robot_enhancement_batch])
    enhancement_repo = fake_repository(
        init_entries=[
            PendingEnhancement(
                id=uuid7(),
                robot_enhancement_batch_id=robot_enhancement_batch.id,
                reference_id=uuid7(),
                robot_id=test_robot.id,
                enhancement_request_id=uuid7(),
                status=PendingEnhancementStatus.PROCESSING,
                expires_at=initial_expiry,
            )
        ]
    )
    uow = fake_uow(
        robot_enhancement_batches=repo, pending_enhancements=enhancement_repo
    )
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    updated, new_expiry = await service.renew_robot_enhancement_batch_lease(
        robot_enhancement_batch_id=robot_enhancement_batch.id,
        lease_duration=updated_lease,
    )

    assert updated == 1

    expected_new_expiry = utc_now() + updated_lease
    assert abs(new_expiry - expected_new_expiry) < datetime.timedelta(seconds=1)

    updated_pending_enhancement = enhancement_repo.get_first_record()
    assert abs(
        updated_pending_enhancement.expires_at - expected_new_expiry
    ) < datetime.timedelta(seconds=1)


@pytest.mark.asyncio
async def test_expire_and_replace_stale_pending_enhancements_no_expired(
    fake_repository, fake_uow, test_robot
):
    """Test when there are no expired pending enhancements."""
    # Create pending enhancements that are NOT expired
    future_expiry = utc_now() + datetime.timedelta(hours=1)
    pending_enhancements = [
        PendingEnhancement(
            id=uuid7(),
            reference_id=uuid7(),
            robot_id=test_robot.id,
            source="test-source",
            status=PendingEnhancementStatus.PROCESSING,
            expires_at=future_expiry,
        )
        for _ in range(3)
    ]

    class FakePendingEnhancementRepo(fake_repository):
        async def expire_pending_enhancements_past_expiry(self, now, statuses):
            """Atomically find and expire pending enhancements."""
            expired = [
                pe
                for pe in self.repository.values()
                if pe.expires_at < now and pe.status in statuses
            ]
            for pe in expired:
                pe.status = PendingEnhancementStatus.EXPIRED
            return expired

    repo = FakePendingEnhancementRepo(init_entries=pending_enhancements)
    uow = fake_uow(pending_enhancements=repo)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    result = await service.expire_and_replace_stale_pending_enhancements()

    assert result["expired"] == 0
    assert result["replaced_with"] == 0

    # Verify nothing was changed
    for pe in pending_enhancements:
        updated = await repo.get_by_pk(pe.id)
        assert updated.status == PendingEnhancementStatus.PROCESSING


@pytest.mark.asyncio
async def test_expire_and_replace_stale_pending_enhancements_with_expired(
    fake_repository, fake_uow, test_robot
):
    """Test expiring and creating retries for expired pending enhancements."""
    # Create expired pending enhancements (PROCESSING status, past expiry)
    past_expiry = utc_now() - datetime.timedelta(minutes=5)
    enhancement_request_id = uuid7()
    expired_enhancements = [
        PendingEnhancement(
            id=uuid7(),
            reference_id=uuid7(),
            robot_id=test_robot.id,
            enhancement_request_id=enhancement_request_id,
            source="test-source",
            status=PendingEnhancementStatus.PROCESSING,
            expires_at=past_expiry,
        )
        for _ in range(3)
    ]

    # Add a non-expired one that should be ignored
    future_expiry = utc_now() + datetime.timedelta(hours=1)
    non_expired = PendingEnhancement(
        id=uuid7(),
        reference_id=uuid7(),
        robot_id=test_robot.id,
        source="test-source",
        status=PendingEnhancementStatus.PROCESSING,
        expires_at=future_expiry,
    )

    # Add a PENDING one that's past expiry (should be ignored - only PROCESSING expire)
    pending_past_expiry = PendingEnhancement(
        id=uuid7(),
        reference_id=uuid7(),
        robot_id=test_robot.id,
        source="test-source",
        status=PendingEnhancementStatus.PENDING,
        expires_at=past_expiry,
    )

    all_enhancements = [*expired_enhancements, non_expired, pending_past_expiry]

    class FakePendingEnhancementRepo(fake_repository):
        async def count_retry_depth(self, pending_enhancement_id):
            """Return 0 for all (no previous retries)."""
            return 0

        async def expire_pending_enhancements_past_expiry(self, now, statuses):
            """Atomically find and expire pending enhancements."""
            expired = [
                pe
                for pe in self.repository.values()
                if pe.expires_at < now and pe.status in statuses
            ]
            # Update status to EXPIRED for matched records
            for pe in expired:
                pe.status = PendingEnhancementStatus.EXPIRED
            return expired

    repo = FakePendingEnhancementRepo(init_entries=all_enhancements)
    uow = fake_uow(pending_enhancements=repo)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    result = await service.expire_and_replace_stale_pending_enhancements(
        max_retry_count=3
    )

    assert result["expired"] == 3
    assert result["replaced_with"] == 3

    # Verify expired ones are now EXPIRED
    for pe in expired_enhancements:
        updated = await repo.get_by_pk(pe.id)
        assert updated.status == PendingEnhancementStatus.EXPIRED

    # Verify non-expired is still PROCESSING
    non_expired = await repo.get_by_pk(non_expired.id)
    assert non_expired.status == PendingEnhancementStatus.PROCESSING

    # Verify pending past expiry is still PENDING (not expired)
    pending = await repo.get_by_pk(pending_past_expiry.id)
    assert pending.status == PendingEnhancementStatus.PENDING

    # Verify new pending enhancements were created
    all_records = await repo.get_all()
    new_pending = [
        pe
        for pe in all_records
        if pe.status == PendingEnhancementStatus.PENDING and pe.retry_of is not None
    ]
    assert len(new_pending) == 3

    # Verify retry_of links to expired enhancements and metadata is preserved
    expired_ids = {pe.id for pe in expired_enhancements}
    for new_pe in new_pending:
        assert new_pe.retry_of in expired_ids
        original = next(pe for pe in expired_enhancements if pe.id == new_pe.retry_of)
        assert new_pe.reference_id == original.reference_id
        assert new_pe.robot_id == original.robot_id
        # Verify metadata
        assert new_pe.enhancement_request_id == enhancement_request_id
        assert new_pe.source == "test-source"
        assert new_pe.status == PendingEnhancementStatus.PENDING


@pytest.mark.asyncio
async def test_process_reference_duplicate_decision_non_terminal_state(
    fake_repository, fake_uow
):
    """
    Test that non-terminal states skip map_duplicate_decision.

    When determine_canonical_from_candidates returns UNRESOLVED (a non-terminal state),
    the method should not call map_duplicate_decision, which would raise an error.
    """
    reference_id = uuid.uuid4()
    decision_id = uuid.uuid4()

    # Create a decision that will end up as UNRESOLVED
    decision = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )

    # Decision after nominate_candidate_canonicals
    decision_after_nominate = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )

    # Decision after determine_canonical_from_candidates - returns UNRESOLVED (non-terminal)
    decision_unresolved = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.UNRESOLVED,
    )

    uow = fake_uow()
    es_uow = fake_uow()
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, es_uow
    )

    with (
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "shortcut_deduplication_using_identifiers",
            AsyncMock(return_value=None),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "nominate_candidate_canonicals",
            AsyncMock(return_value=decision_after_nominate),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "determine_canonical_from_candidates",
            AsyncMock(return_value=decision_unresolved),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "map_duplicate_decision",
            AsyncMock(),
        ) as mock_map,
        patch.object(
            service,
            "apply_reference_duplicate_decision_side_effects",
            AsyncMock(),
        ) as mock_side_effects,
    ):
        # This should NOT raise "Only terminal duplicate determinations can be mapped"
        await service.process_reference_duplicate_decision(decision)

        # map_duplicate_decision should NOT be called for non-terminal states
        mock_map.assert_not_awaited()

        # Side effects should also NOT be called for non-terminal states
        mock_side_effects.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_reference_duplicate_decision_terminal_state(
    fake_repository, fake_uow
):
    """
    Test that terminal states DO call map_duplicate_decision and side effects.

    When determine_canonical_from_candidates returns CANONICAL (a terminal state),
    the method should call map_duplicate_decision and apply side effects.
    """
    reference_id = uuid.uuid4()
    decision_id = uuid.uuid4()

    decision = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )

    decision_after_nominate = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.PENDING,
    )

    # Decision after determine_canonical_from_candidates - returns CANONICAL (terminal)
    decision_canonical = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
    )

    # Decision after map
    decision_mapped = ReferenceDuplicateDecision(
        id=decision_id,
        reference_id=reference_id,
        duplicate_determination=DuplicateDetermination.CANONICAL,
    )

    uow = fake_uow()
    es_uow = fake_uow()
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, es_uow
    )

    with (
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "shortcut_deduplication_using_identifiers",
            AsyncMock(return_value=None),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "nominate_candidate_canonicals",
            AsyncMock(return_value=decision_after_nominate),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "determine_canonical_from_candidates",
            AsyncMock(return_value=decision_canonical),
        ),
        patch.object(
            service._deduplication_service,  # noqa: SLF001
            "map_duplicate_decision",
            AsyncMock(return_value=(decision_mapped, True)),
        ) as mock_map,
        patch.object(
            service,
            "apply_reference_duplicate_decision_side_effects",
            AsyncMock(),
        ) as mock_side_effects,
    ):
        await service.process_reference_duplicate_decision(decision)

        # map_duplicate_decision SHOULD be called for terminal states
        mock_map.assert_awaited_once_with(decision_canonical)

        # Side effects SHOULD be called for terminal states
        mock_side_effects.assert_awaited_once()


@pytest.mark.asyncio
async def test_expire_and_replace_stale_pending_enhancements_at_retry_limit(
    fake_repository, fake_uow, test_robot, caplog
):
    """Test that enhancements at retry limit are not retried."""
    past_expiry = utc_now() - datetime.timedelta(minutes=5)

    expired_low_depth = PendingEnhancement(
        id=uuid7(),
        reference_id=uuid7(),
        robot_id=test_robot.id,
        source="test-source",
        status=PendingEnhancementStatus.PROCESSING,
        expires_at=past_expiry,
    )

    expired_at_limit = PendingEnhancement(
        id=uuid7(),
        reference_id=uuid7(),
        robot_id=test_robot.id,
        source="test-source",
        status=PendingEnhancementStatus.PROCESSING,
        expires_at=past_expiry,
    )

    expired_over_limit = PendingEnhancement(
        id=uuid7(),
        reference_id=uuid7(),
        robot_id=test_robot.id,
        source="test-source",
        status=PendingEnhancementStatus.PROCESSING,
        expires_at=past_expiry,
    )

    all_enhancements = [expired_low_depth, expired_at_limit, expired_over_limit]

    # Create repository that returns different retry depths
    class FakePendingEnhancementRepo(fake_repository):
        async def count_retry_depth(self, pending_enhancement_id):
            """Return different depths based on ID."""
            if pending_enhancement_id == expired_low_depth.id:
                return 1  # Below limit
            if pending_enhancement_id == expired_at_limit.id:
                return 3  # At limit
            return 4  # Over limit

        async def expire_pending_enhancements_past_expiry(self, now, statuses):
            """Atomically find and expire pending enhancements."""
            expired = [
                pe
                for pe in self.repository.values()
                if pe.expires_at < now and pe.status in statuses
            ]
            for pe in expired:
                pe.status = PendingEnhancementStatus.EXPIRED
            return expired

    repo = FakePendingEnhancementRepo(init_entries=all_enhancements)
    uow = fake_uow(pending_enhancements=repo)
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    result = await service.expire_and_replace_stale_pending_enhancements(
        max_retry_count=3
    )

    assert result["expired"] == 3
    assert result["replaced_with"] == 1

    # Verify all are marked EXPIRED
    for pe in all_enhancements:
        updated = await repo.get_by_pk(pe.id)
        assert updated.status == PendingEnhancementStatus.EXPIRED

    # Verify only one new pending enhancement was created
    all_records = await repo.get_all()
    new_pending = [
        pe
        for pe in all_records
        if pe.status == PendingEnhancementStatus.PENDING and pe.retry_of is not None
    ]
    assert len(new_pending) == 1
    assert new_pending[0].retry_of == expired_low_depth.id

    warning_logs = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and "Pending enhancement exceeded retry limit" in record.getMessage()
    ]
    assert len(warning_logs) == 2
