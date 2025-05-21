import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import status

from app.core.exceptions import (
    NotFoundError,
    RobotEnhancementError,
    SQLNotFoundError,
    WrongReferenceError,
)
from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    Reference,
    Visibility,
)
from app.domain.robots.models import Robots
from app.domain.robots.service import RobotService

ENHANCEMENT_DATA = {
    "source": "test_source",
    "visibility": "public",
    "content_version": uuid.uuid4(),
    "enhancement_type": "annotation",
    "content": {
        "enhancement_type": "annotation",
        "annotations": [
            {
                "annotation_type": "test_annotation",
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
    # Mock the robot service
    fake_robot_service = AsyncMock()
    fake_robot_service.request_enhancement_from_robot.return_value = httpx.Response(
        status_code=status.HTTP_202_ACCEPTED
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

    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests, references=fake_references
    )

    service = EnhancementService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=uuid.uuid4(), enhancement_parameters={}
    )

    enhancement_request = await service.request_reference_enhancement(
        enhancement_request=received_enhancement_request,
        robot_service=fake_robot_service,
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
    fake_robot_service = AsyncMock()
    fake_robot_service.request_enhancement_from_robot.side_effect = (
        RobotEnhancementError('{"message":"broken"}')
    )

    reference_id = uuid.uuid4()
    fake_references = fake_repository(
        init_entries=[
            Reference(id=reference_id, visibility=Visibility.PUBLIC, identifiers=[])
        ]
    )
    fake_enhancement_requests = fake_repository()

    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests, references=fake_references
    )

    service = EnhancementService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=uuid.uuid4(), enhancement_parameters={}
    )

    enhancement_request = await service.request_reference_enhancement(
        enhancement_request=received_enhancement_request,
        robot_service=fake_robot_service,
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

    uow = fake_uow(enhancement_requests=fake_repository(), references=fake_repository())

    service = EnhancementService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=unknown_reference_id,
        robot_id=uuid.uuid4(),
        enhancement_parameters={},
    )

    with pytest.raises(SQLNotFoundError):
        await service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
            robot_service=RobotService(uow, Robots({})),
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
        enhancement_requests=fake_enhancement_requests, references=fake_references
    )

    service = EnhancementService(uow)

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=uuid.uuid4(), enhancement_parameters={}
    )

    with pytest.raises(NotFoundError):
        await service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
            robot_service=RobotService(uow, Robots({})),
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
    service = EnhancementService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert returned_enhancement_request == existing_enhancement_request


@pytest.mark.asyncio
async def test_get_enhancement_request_doesnt_exist(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = EnhancementService(uow)

    with pytest.raises(
        SQLNotFoundError,
        match=f"{enhancement_request_id} not in repository",
    ):
        await service.get_enhancement_request(enhancement_request_id)


@pytest.mark.asyncio
async def test_create_reference_enhancement_happy_path(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()
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
        references=fake_repository([Reference(id=reference_id)]),
        enhancements=fake_enhancement_repo,
    )

    service = EnhancementService(uow)

    enhancement_request = await service.create_reference_enhancement(
        enhancement_request_id=existing_enhancement_request.id,
        enhancement=Enhancement(reference_id=reference_id, **ENHANCEMENT_DATA),
    )

    created_enhancement = fake_enhancement_repo.get_first_record()

    assert enhancement_request.request_status == EnhancementRequestStatus.COMPLETED
    assert created_enhancement.source == ENHANCEMENT_DATA.get("source")


@pytest.mark.asyncio
async def test_create_reference_enhancement_reference_not_found(
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

    service = EnhancementService(uow)

    with pytest.raises(SQLNotFoundError):
        await service.create_reference_enhancement(
            enhancement_request_id=existing_enhancement_request.id,
            enhancement=Enhancement(
                reference_id=non_existent_reference_id, **ENHANCEMENT_DATA
            ),
        )


@pytest.mark.asyncio
async def test_create_reference_enhancement_enhancement_request_not_found(
    fake_repository, fake_uow
):
    reference_id = uuid.uuid4()

    uow = fake_uow(
        enhancement_requests=fake_repository(),
        references=fake_repository([Reference(id=reference_id)]),
        enhancements=fake_repository(),
    )

    service = EnhancementService(uow)

    with pytest.raises(SQLNotFoundError):
        await service.create_reference_enhancement(
            enhancement_request_id=uuid.uuid4(),
            enhancement=Enhancement(reference_id=reference_id, **ENHANCEMENT_DATA),
        )


@pytest.mark.asyncio
async def test_create_reference_enhancement_enhancement_for_wrong_reference(
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

    service = EnhancementService(uow)

    with pytest.raises(WrongReferenceError):
        await service.create_reference_enhancement(
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
    service = EnhancementService(uow)

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
    service = EnhancementService(uow)

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
    service = EnhancementService(uow)

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
    service = EnhancementService(uow)

    with pytest.raises(
        SQLNotFoundError, match=f"{{'{missing_reference_id}'}} not in repository"
    ):
        await service.register_batch_reference_enhancement_request(
            enhancement_request=batch_enhancement_request
        )
