"""Unit tests for the ReferenceService class."""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import status

from app.core.exceptions import (
    RobotEnhancementError,
    SQLNotFoundError,
    WrongReferenceError,
)
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    ExternalIdentifierAdapter,
    Reference,
    Visibility,
)
from app.domain.references.service import ReferenceService
from app.domain.robots.models import Robot
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService


@pytest.mark.asyncio
async def test_get_reference_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo = fake_repository(init_entries=[dummy_reference])
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    result = await service.get_reference(dummy_id)
    assert result.id == dummy_reference.id


@pytest.mark.asyncio
async def test_get_reference_not_found(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    dummy_id = uuid.uuid4()
    with pytest.raises(SQLNotFoundError):
        await service.get_reference(dummy_id)


@pytest.mark.asyncio
async def test_register_reference_happy_path(fake_repository, fake_uow):
    repo = fake_repository()
    uow = fake_uow(references=repo)
    service = ReferenceService(uow)
    created = await service.register_reference()
    # Verify that an id was assigned during registration.
    assert hasattr(created, "id")
    assert isinstance(created.id, uuid.UUID)


@pytest.mark.asyncio
async def test_add_identifier_happy_path(fake_repository, fake_uow):
    dummy_id = uuid.uuid4()
    dummy_reference = Reference(id=dummy_id)
    repo_refs = fake_repository(init_entries=[dummy_reference])
    repo_ids = fake_repository()
    uow = fake_uow(references=repo_refs, external_identifiers=repo_ids)
    service = ReferenceService(uow)
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
    service = ReferenceService(uow)
    dummy_id = uuid.uuid4()
    fake_identifier_create = ExternalIdentifierAdapter.validate_python(
        {"identifier": "W1234", "identifier_type": "open_alex"}
    )
    with pytest.raises(SQLNotFoundError):
        await service.add_identifier(dummy_id, fake_identifier_create)


ENHANCEMENT_DATA = {
    "source": "test_source",
    "visibility": "public",
    "enhancement_type": "annotation",
    "content": {
        "enhancement_type": "annotation",
        "annotations": [
            {
                "annotation_type": "boolean",
                "scheme": "openalex:topic",
                "value": "true",
                "label": "test_label",
                "data": {"foo": "bar"},
            }
        ],
    },
}


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_happy_path(
    fake_repository, fake_uow
):
    # Mock the robot dispatcher
    fake_robot_request_dispatcher = AsyncMock()
    fake_robot_request_dispatcher.send_enhancement_request_to_robot.return_value = (
        httpx.Response(status_code=status.HTTP_202_ACCEPTED)
    )

    reference_id = uuid.uuid4()
    fake_references = fake_repository(
        init_entries=[
            Reference(
                id=reference_id,
                visibility=Visibility.PUBLIC,
                identifiers=[],
            )
        ]
    )
    fake_enhancement_requests = fake_repository()

    robot_id = uuid.uuid4()
    fake_robots = fake_repository(
        init_entries=[
            Robot(
                id=robot_id,
                base_url="https://www.robothere.org/",
                client_secret="fdkjglkdfjglfksdgf",
                description="description",
                name="name",
                owner="owner",
            )
        ]
    )

    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_references,
        robots=fake_robots,
    )

    referece_service = ReferenceService(uow)
    robot_service = RobotService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=robot_id, enhancement_parameters={}
    )

    enhancement_request = await referece_service.request_reference_enhancement(
        enhancement_request=received_enhancement_request,
        robot_service=robot_service,
        robot_request_dispatcher=fake_robot_request_dispatcher,
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.ACCEPTED


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_rejected(
    fake_uow, fake_repository
):
    """
    A robot rejects a request to create an enhancement against a reference.
    """
    fake_robot_request_dispatcher = AsyncMock()
    fake_robot_request_dispatcher.send_enhancement_request_to_robot.side_effect = (
        RobotEnhancementError('{"message":"broken"}')
    )

    reference_id = uuid.uuid4()
    fake_references = fake_repository(
        init_entries=[
            Reference(id=reference_id, visibility=Visibility.PUBLIC, identifiers=[])
        ]
    )
    fake_enhancement_requests = fake_repository()

    robot_id = uuid.uuid4()
    fake_robots = fake_repository(
        init_entries=[
            Robot(
                id=robot_id,
                base_url="https://www.robothere.org/",
                client_secret="fdkjglkdfjglfksdgf",
                description="description",
                name="name",
                owner="owner",
            )
        ]
    )

    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_references,
        robots=fake_robots,
    )

    reference_service = ReferenceService(uow)
    robot_service = RobotService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=robot_id, enhancement_parameters={}
    )

    enhancement_request = await reference_service.request_reference_enhancement(
        enhancement_request=received_enhancement_request,
        robot_service=robot_service,
        robot_request_dispatcher=fake_robot_request_dispatcher,
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.REJECTED
    assert enhancement_request.error == '{"message":"broken"}'


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_nonexistent_reference(
    fake_uow, fake_repository
):
    """
    Enhancement requested against nonexistent reference
    """
    unknown_reference_id = uuid.uuid4()

    uow = fake_uow(
        enhancement_requests=fake_repository(),
        references=fake_repository(),
        robots=fake_repository(),
    )

    reference_service = ReferenceService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=unknown_reference_id,
        robot_id=uuid.uuid4(),
        enhancement_parameters={},
    )

    with pytest.raises(SQLNotFoundError):
        await reference_service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
            robot_service=RobotService(uow),
            robot_request_dispatcher=RobotRequestDispatcher(),
        )


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_nonexistent_robot(
    fake_uow, fake_repository
):
    """
    Enhancement requested against a robot that does not exist.
    """
    # Mock the robot service
    reference_id = uuid.uuid4()
    fake_references = fake_repository(
        init_entries=[
            Reference(id=reference_id, visibility=Visibility.PUBLIC, identifiers=[])
        ]
    )
    fake_enhancement_requests = fake_repository()

    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_references,
        robots=fake_repository(),
    )

    reference_service = ReferenceService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=uuid.uuid4(), enhancement_parameters={}
    )

    with pytest.raises(SQLNotFoundError):
        await reference_service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
            robot_service=RobotService(uow),
            robot_request_dispatcher=RobotRequestDispatcher(),
        )


@pytest.mark.asyncio
async def test_get_enhancement_request_happy_path(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={"some": "parameters"},
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = ReferenceService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert returned_enhancement_request == existing_enhancement_request


@pytest.mark.asyncio
async def test_get_enhancement_request_doesnt_exist(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = ReferenceService(uow)

    with pytest.raises(
        SQLNotFoundError,
        match=f"{enhancement_request_id} not in repository",
    ):
        await service.get_enhancement_request(enhancement_request_id)


@pytest.mark.asyncio
async def test_create_reference_enhancement_from_request_happy_path(
    fake_repository, fake_uow
):
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()
    fake_reference_repo = fake_repository([Reference(id=reference_id)])
    fake_reference_repo_es = fake_repository()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=reference_id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_reference_repo,
    )
    es_uow = fake_uow(references=fake_reference_repo_es)

    service = ReferenceService(sql_uow=uow, es_uow=es_uow)
    enhancement_request = await service.create_reference_enhancement_from_request(
        enhancement_request_id=existing_enhancement_request.id,
        enhancement=Enhancement(reference_id=reference_id, **ENHANCEMENT_DATA),
    )

    reference = fake_reference_repo.get_first_record()

    assert enhancement_request.request_status == EnhancementRequestStatus.COMPLETED
    assert reference.enhancements[0]["source"] == ENHANCEMENT_DATA.get("source")

    es_reference = fake_reference_repo_es.get_first_record()

    assert es_reference == reference


@pytest.mark.asyncio
async def test_create_reference_enhancement_from_request_reference_not_found(
    fake_repository, fake_uow
):
    enhancement_request_id = uuid.uuid4()
    non_existent_reference_id = uuid.uuid4()
    fake_enhancement_repo = fake_repository()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=non_existent_reference_id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_repository(),
        enhancements=fake_enhancement_repo,
    )

    service = ReferenceService(uow)

    with pytest.raises(SQLNotFoundError):
        await service.create_reference_enhancement_from_request(
            enhancement_request_id=existing_enhancement_request.id,
            enhancement=Enhancement(
                reference_id=non_existent_reference_id, **ENHANCEMENT_DATA
            ),
        )


@pytest.mark.asyncio
async def test_create_reference_enhancement_from_request_enhancement_request_not_found(
    fake_repository, fake_uow
):
    reference_id = uuid.uuid4()

    uow = fake_uow(
        enhancement_requests=fake_repository(),
        references=fake_repository([Reference(id=reference_id)]),
        enhancements=fake_repository(),
    )

    service = ReferenceService(uow)

    with pytest.raises(SQLNotFoundError):
        await service.create_reference_enhancement_from_request(
            enhancement_request_id=uuid.uuid4(),
            enhancement=Enhancement(reference_id=reference_id, **ENHANCEMENT_DATA),
        )


@pytest.mark.asyncio
async def test_create_reference_enhancement_from_request_enhancement_for_wrong_reference(  # noqa: E501
    fake_repository, fake_uow
):
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()
    different_reference_id = uuid.uuid4()
    fake_enhancement_repo = fake_repository()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=reference_id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_repository(
            [Reference(id=reference_id), Reference(id=different_reference_id)]
        ),
        enhancements=fake_enhancement_repo,
    )

    service = ReferenceService(uow)

    with pytest.raises(WrongReferenceError):
        await service.create_reference_enhancement_from_request(
            enhancement_request_id=existing_enhancement_request.id,
            enhancement=Enhancement(
                reference_id=different_reference_id, **ENHANCEMENT_DATA
            ),
        )


@pytest.mark.asyncio
async def test_mark_enhancement_request_as_failed(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
    )
    service = ReferenceService(uow)

    returned_enhancement_request = await service.mark_enhancement_request_failed(
        enhancement_request_id=enhancement_request_id, error="it broke"
    )

    assert (
        returned_enhancement_request.request_status == EnhancementRequestStatus.FAILED
    )
    assert returned_enhancement_request.error == "it broke"


@pytest.mark.asyncio
async def test_mark_enhancement_request_as_failed_request_non_existent(
    fake_repository, fake_uow
):
    missing_enhancement_request_id = uuid.uuid4()

    uow = fake_uow(
        enhancement_requests=fake_repository(),
    )
    service = ReferenceService(uow)

    with pytest.raises(SQLNotFoundError):
        await service.mark_enhancement_request_failed(
            enhancement_request_id=missing_enhancement_request_id, error="it broke"
        )


@pytest.mark.asyncio
async def test_register_batch_reference_enhancement_request(fake_repository, fake_uow):
    """
    Test the happy path for registering a batch enhancement request.
    """
    batch_request_id = uuid.uuid4()
    reference_ids = [uuid.uuid4(), uuid.uuid4()]
    robot_id = uuid.uuid4()
    batch_enhancement_request = BatchEnhancementRequest(
        id=batch_request_id,
        reference_ids=reference_ids,
        robot_id=robot_id,
        enhancement_parameters={"param": "value"},
    )

    fake_batch_requests = fake_repository()
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )

    uow = fake_uow(
        batch_enhancement_requests=fake_batch_requests,
        references=fake_references,
    )
    service = ReferenceService(uow)

    created_request = await service.register_batch_reference_enhancement_request(
        enhancement_request=batch_enhancement_request
    )

    stored_request = fake_batch_requests.get_first_record()

    assert created_request == stored_request
    assert created_request.reference_ids == reference_ids
    assert created_request.enhancement_parameters == {"param": "value"}


@pytest.mark.asyncio
async def test_register_batch_reference_enhancement_request_missing_pk(
    fake_repository, fake_uow
):
    """
    Test registering a batch enhancement request with a missing reference ID.
    """
    batch_request_id = uuid.uuid4()
    reference_ids = [uuid.uuid4(), uuid.uuid4()]
    missing_reference_id = uuid.uuid4()
    robot_id = uuid.uuid4()
    batch_enhancement_request = BatchEnhancementRequest(
        id=batch_request_id,
        reference_ids=[*reference_ids, missing_reference_id],
        robot_id=robot_id,
        enhancement_parameters={"param": "value"},
    )

    fake_batch_requests = fake_repository()
    fake_references = fake_repository(
        init_entries=[Reference(id=ref_id) for ref_id in reference_ids]
    )

    uow = fake_uow(
        batch_enhancement_requests=fake_batch_requests,
        references=fake_references,
    )
    service = ReferenceService(uow)

    with pytest.raises(
        SQLNotFoundError, match=f"{{'{missing_reference_id}'}} not in repository"
    ):
        await service.register_batch_reference_enhancement_request(
            enhancement_request=batch_enhancement_request
        )
