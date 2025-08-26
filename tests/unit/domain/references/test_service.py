"""Unit tests for the ReferenceService class."""

import uuid

import pytest

from app.core.config import ESPercolationOperation
from app.core.exceptions import (
    InvalidParentEnhancementError,
    SQLNotFoundError,
)
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierAdapter,
    Reference,
    RobotAutomationPercolationResult,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)


@pytest.mark.asyncio
async def test_get_reference_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo)
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)
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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)
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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)
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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

    enhancement_to_add = Enhancement(
        reference_id=dummy_reference.id,  # different reference id
        derived_from=[dummy_parent_enhancement.id],
        **fake_enhancement_data,
    )

    with pytest.raises(
        InvalidParentEnhancementError, match="different parent reference"
    ):
        await service.add_enhancement(enhancement_to_add)


@pytest.mark.asyncio
async def test_register_reference_enhancement_request(fake_repository, fake_uow):
    """
    Test the happy path for registering an enhancement request.
    """
    reference_ids = [uuid.uuid4(), uuid.uuid4()]
    robot_id = uuid.uuid4()
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=reference_ids,
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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

    created_request = await service.register_reference_enhancement_request(
        enhancement_request=enhancement_request
    )

    stored_request = fake_requests.get_first_record()

    assert created_request == stored_request
    assert created_request.reference_ids == reference_ids
    assert created_request.enhancement_parameters == {"param": "value"}


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
    service = ReferenceService(ReferenceAntiCorruptionService(fake_repository()), uow)

    with pytest.raises(
        SQLNotFoundError, match=f"{{'{missing_reference_id}'}} not in repository"
    ):
        await service.register_reference_enhancement_request(
            enhancement_request=enhancement_request
        )


@pytest.mark.asyncio
async def test_detect_robot_automations(
    fake_repository, fake_uow, fake_enhancement_data, monkeypatch
):
    """Test the detection of robot automations for references."""
    # Patch settings to test chunking
    monkeypatch.setattr(
        "app.domain.references.service.settings.es_percolation_chunk_size_override",
        {ESPercolationOperation.ROBOT_AUTOMATION: 2},
    )

    reference_id = uuid.uuid4()
    robot_id = uuid.uuid4()

    enhancement = Enhancement(reference_id=reference_id, **fake_enhancement_data)
    hydrated_references = [
        Reference(id=reference_id, visibility="public", enhancements=[enhancement]),
        Reference(id=uuid.uuid4(), visibility="public", enhancements=[enhancement]),
        Reference(id=uuid.uuid4(), visibility="public", enhancements=[enhancement]),
    ]

    # Extend the fake repository with get_hydrated and percolation
    class FakeRepo(fake_repository):
        def __init__(self, init_entries=None):
            super().__init__(init_entries=init_entries)
            self.hydrated_references = init_entries

        async def get_hydrated(
            self,
            reference_ids,
            enhancement_types=None,
            external_identifier_types=None,
        ):
            return await self.get_by_pks(reference_ids)

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
    fake_references_repo = FakeRepo(hydrated_references)
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
        reference_ids=[r.id for r in hydrated_references],
        enhancement_ids=[enhancement.id],
    )
    assert len(results) == 1
    assert results[0].robot_id == robot_id
    # Checks that the robot automations were marged (shared reference id on the
    # enhancement and a reference)
    assert len(results[0].reference_ids) == 3
