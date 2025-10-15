"""Unit tests for the ReferenceService class."""

import json
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
from destiny_sdk.enhancements import BibliographicMetadataEnhancement
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import ReferenceFileInput

from app.core.exceptions import (
    InvalidParentEnhancementError,
    RobotEnhancementError,
    RobotUnreachableError,
    SQLNotFoundError,
)
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
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
from app.domain.robots.service import RobotService
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.persistence.blob.models import BlobStorageFile


@pytest.fixture
def test_robot():
    return Robot(
        base_url="http://127.0.0.1:8001",
        description="fake robot for unit test",
        name="Test Robot",
        owner="test",
    )


@pytest.mark.asyncio
async def test_get_reference_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
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
    dummy_id = uuid.uuid4()
    with pytest.raises(SQLNotFoundError):
        await service.get_reference(dummy_id)


@pytest.mark.asyncio
async def test_add_identifier_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
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
    dummy_id = uuid.uuid4()
    fake_identifier_create = ExternalIdentifierAdapter.validate_python(
        {"identifier": "W1234", "identifier_type": "open_alex"}
    )
    with pytest.raises(SQLNotFoundError):
        await service.add_identifier(dummy_id, fake_identifier_create)


@pytest.mark.asyncio
async def test_add_enhancement_happy_path(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid.uuid4())
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
    assert Enhancement(**reference_enhancements[0]).id == enhancement_to_add.id


@pytest.mark.asyncio
async def test_add_enhancement_reference_does_not_exist(
    fake_repository, fake_uow, fake_enhancement_data
):
    uow = fake_uow(references=fake_repository())
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=uuid.uuid4(),  # Doesn't exist
        **fake_enhancement_data,
    )

    with pytest.raises(SQLNotFoundError):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_add_enhancement_derived_from_does_not_exist(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid.uuid4())
    repo_refs = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo_refs, enhancements=fake_repository())
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, fake_uow()
    )

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id,
        derived_from=[uuid.uuid4()],
        **fake_enhancement_data,
    )

    with pytest.raises(InvalidParentEnhancementError):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_add_enhancement_derived_from_enhancement_for_different_reference(
    fake_repository, fake_uow, fake_enhancement_data
):
    dummy_reference = Reference(id=uuid.uuid4())
    repo_refs = fake_repository(init_entries=[dummy_reference])

    dummy_parent_enhancement = Enhancement(
        reference_id=uuid.uuid4(),  # Not the reference we'll enhance
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
    dup_ref_id = uuid.uuid4()
    dummy_reference = Reference(
        id=uuid.uuid4(), duplicate_references=[Reference(id=dup_ref_id)]
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
    assert reference.enhancements[0]["id"] == enhancement_to_add.id


@pytest.mark.asyncio
async def test_register_reference_enhancement_request(fake_repository, fake_uow):
    """
    Test the happy path for registering an enhancement request.
    """
    reference_ids = [uuid.uuid4(), uuid.uuid4()]
    robot_id = uuid.uuid4()
    request_id = uuid.uuid4()
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
    reference_ids = [uuid.uuid4(), uuid.uuid4()]
    missing_reference_id = uuid.uuid4()
    robot_id = uuid.uuid4()
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
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
async def test_collect_and_dispatch_references_for_enhancement_happy_path(
    fake_repository, fake_uow, test_robot
):
    """Test collecting and dispatching references for enhancement"""
    mock_blob_repository = AsyncMock()
    mock_blob_repository.get_signed_url.return_value = "http://127.0.0.1:8001"

    reference_ids = [uuid.uuid4() for _ in range(3)]

    enhancement_request = EnhancementRequest(
        reference_ids=reference_ids,
        robot_id=test_robot.id,
        request_status=EnhancementRequestStatus.RECEIVED,
        enhancement_parameters={"param": "value"},
    )

    fake_robots = fake_repository(init_entries=[test_robot])
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )
    fake_requests = fake_repository(init_entries=[enhancement_request])

    uow = fake_uow(
        enhancement_requests=fake_requests,
        robots=fake_robots,
        references=fake_references,
    )

    mock_robot_request_dispatcher = AsyncMock()

    service = ReferenceService(
        ReferenceAntiCorruptionService(mock_blob_repository), uow, fake_uow()
    )

    await service.collect_and_dispatch_references_for_enhancement(
        enhancement_request=enhancement_request,
        robot_service=RobotService(RobotAntiCorruptionService(), uow),
        robot_request_dispatcher=mock_robot_request_dispatcher,
        blob_repository=mock_blob_repository,
    )

    # Assert we've send a request to the robot
    mock_robot_request_dispatcher.send_enhancement_request_to_robot.assert_called_once()

    # Assert no errors thrown
    assert enhancement_request.request_status == EnhancementRequestStatus.ACCEPTED


@pytest.mark.asyncio
async def test_collect_and_dispatch_references_for_enhancement_robot_unreachable(
    fake_repository, fake_uow, test_robot
):
    """Test enhancement request is marked as failed if robot is unreachable."""
    mock_blob_repository = AsyncMock()
    mock_blob_repository.get_signed_url.return_value = "http://127.0.0.1:8001"

    reference_ids = [uuid.uuid4() for _ in range(3)]

    enhancement_request = EnhancementRequest(
        reference_ids=reference_ids,
        robot_id=test_robot.id,
        request_status=EnhancementRequestStatus.RECEIVED,
        enhancement_parameters={"param": "value"},
    )

    fake_robots = fake_repository(init_entries=[test_robot])
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )
    fake_requests = fake_repository(init_entries=[enhancement_request])

    uow = fake_uow(
        enhancement_requests=fake_requests,
        robots=fake_robots,
        references=fake_references,
    )

    mock_robot_request_dispatcher = AsyncMock()
    mock_robot_request_dispatcher.send_enhancement_request_to_robot.side_effect = (
        RobotUnreachableError("can't reach robot.")
    )

    service = ReferenceService(
        ReferenceAntiCorruptionService(mock_blob_repository), uow, fake_uow()
    )

    await service.collect_and_dispatch_references_for_enhancement(
        enhancement_request=enhancement_request,
        robot_service=RobotService(RobotAntiCorruptionService(), uow),
        robot_request_dispatcher=mock_robot_request_dispatcher,
        blob_repository=mock_blob_repository,
    )

    # Assert enhancement request has failed
    assert enhancement_request.request_status == EnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_collect_and_dispatch_references_for_enhancement_enhancement_not_possible(
    fake_repository, fake_uow, test_robot
):
    """Test enhancement request is marked as request as rejected if enhancement error"""
    mock_blob_repository = AsyncMock()
    mock_blob_repository.get_signed_url.return_value = "http://127.0.0.1:8001"

    reference_ids = [uuid.uuid4() for _ in range(3)]

    enhancement_request = EnhancementRequest(
        reference_ids=reference_ids,
        robot_id=test_robot.id,
        request_status=EnhancementRequestStatus.RECEIVED,
        enhancement_parameters={"param": "value"},
    )

    fake_robots = fake_repository(init_entries=[test_robot])
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )
    fake_requests = fake_repository(init_entries=[enhancement_request])

    uow = fake_uow(
        enhancement_requests=fake_requests,
        robots=fake_robots,
        references=fake_references,
    )

    mock_robot_request_dispatcher = AsyncMock()
    mock_robot_request_dispatcher.send_enhancement_request_to_robot.side_effect = (
        RobotEnhancementError("can't perform enhancement")
    )

    service = ReferenceService(
        ReferenceAntiCorruptionService(mock_blob_repository), uow, fake_uow()
    )

    await service.collect_and_dispatch_references_for_enhancement(
        enhancement_request=enhancement_request,
        robot_service=RobotService(RobotAntiCorruptionService(), uow),
        robot_request_dispatcher=mock_robot_request_dispatcher,
        blob_repository=mock_blob_repository,
    )

    # Assert enhancement request has failed
    assert enhancement_request.request_status == EnhancementRequestStatus.REJECTED


@pytest.mark.asyncio
@pytest.mark.deduplication_legacy
async def test_ingest_reference_calls_validation_and_merges_legacy(
    fake_repository, fake_uow, monkeypatch
):
    """Test ReferenceService.ingest_reference calls validation and merges reference."""

    monkeypatch.setattr(
        "app.domain.references.service.settings.feature_flags.deduplication", False
    )

    dummy_validation_result = AsyncMock()
    dummy_reference = AsyncMock()
    dummy_validation_result.reference = dummy_reference
    dummy_validation_result.errors = []
    dummy_validation_result.reference_id = "fake-id"

    repo = fake_repository()
    uow = fake_uow(references=repo)
    es_uow = fake_uow()
    service = ReferenceService(
        ReferenceAntiCorruptionService(fake_repository()), uow, es_uow
    )

    with (
        patch.object(
            service._ingestion_service,  # noqa: SLF001
            "validate_and_collide_reference",
            AsyncMock(return_value=(dummy_validation_result, dummy_reference)),
        ) as mock_validate,
        patch.object(service, "_merge_reference", AsyncMock()) as mock_merge,
    ):
        result = await service.ingest_reference("{}", 1, None)
        mock_validate.assert_awaited_once_with("{}", 1, None)
        mock_merge.assert_awaited_once_with(dummy_reference)
        assert result == dummy_validation_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("find_exact_duplicate_return", "should_merge", "expected_decision_id"),
    [
        (None, True, "decision-id"),
        (Mock(id="reference-id"), False, None),
    ],
)
async def test_ingest_reference_deduplication_enabled(
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
        result = await service.ingest_reference("{}", 1, None)
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
    reference_id = uuid.uuid4()
    robot_id = uuid.uuid4()

    enhancement = Enhancement(reference_id=reference_id, **fake_enhancement_data)
    reference = Reference(
        id=reference_id,
        visibility="public",
        enhancements=[enhancement],
        duplicate_references=[],
    )
    reference_2 = Reference(
        id=uuid.uuid4(),
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
    canonical_id = uuid.uuid4()
    content = BibliographicMetadataEnhancement(
        title="Test Title",
        authorship=[],
        publication_year=2024,
        publication_date=None,
    )
    enhancement = Enhancement(
        id=uuid.uuid4(),
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
        duplicate_id = uuid.uuid4()
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


async def test_get_canonical_reference_with_implied_changeset(
    fake_uow, fake_repository
):
    """Test getting canonical reference and implied changeset."""
    duplicate_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
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
    reference_1_id, reference_2_id = uuid.uuid4(), uuid.uuid4()
    enhancement_1 = Enhancement(
        id=uuid.uuid4(),
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
        id=uuid.uuid4(),
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

    references = [Reference(id=uuid.uuid4()) for _ in range(3)]
    pending_enhancements = [
        PendingEnhancement(
            reference_id=ref.id,
            robot_id=test_robot.id,
            enhancement_request_id=uuid.uuid4(),
        )
        for ref in references
    ]

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

    created_batch = await service.create_robot_enhancement_batch(
        robot_id=test_robot.id,
        pending_enhancements=pending_enhancements,
        blob_repository=mock_blob_repository,
    )

    assert isinstance(created_batch, RobotEnhancementBatch)
    assert created_batch.robot_id == test_robot.id

    for pe in pending_enhancements:
        updated_pe = await uow.pending_enhancements.get_by_pk(pe.id)
        assert updated_pe.status == PendingEnhancementStatus.ACCEPTED
        assert updated_pe.robot_enhancement_batch_id == created_batch.id

    mock_blob_repository.upload_file_to_blob_storage.assert_awaited_once()

    args, kwargs = mock_blob_repository.upload_file_to_blob_storage.call_args
    filestream = kwargs["content"]
    file_content = await filestream.read()
    content_lines = file_content.getvalue().decode().strip().split("\n")

    # Verify we have the correct number of references and each has the expected ID
    assert len(content_lines) == len(references)
    for i, line in enumerate(content_lines):
        data = json.loads(line)
        assert data["id"] == str(references[i].id)

    assert created_batch.reference_data_file is not None
    assert created_batch.reference_data_file.endswith(".jsonl")
