import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    Reference,
    Visibility,
)
from app.domain.references.robot_service import RobotService


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_happy_path(
    fake_repository, fake_uow
):
    reference_id = uuid.uuid4()
    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = RobotService(uow)

    fake_reference_service = AsyncMock()
    fake_reference_service.get_reference.return_value = Reference(
        id=reference_id, visibility=Visibility.RESTRICTED
    )

    enhancement_request = await service.request_reference_enhancement(
        reference_id=reference_id,
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        reference_service=fake_reference_service,
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.ACCEPTED


@pytest.mark.asyncio
async def test_request_reference_enhancement_reference_doesnt_exist(
    fake_repository, fake_uow
):
    reference_id = uuid.uuid4()
    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = RobotService(uow)

    fake_reference_service = AsyncMock()
    fake_reference_service.get_reference.return_value = None

    with pytest.raises(RuntimeError):
        await service.request_reference_enhancement(
            reference_id=reference_id,
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            reference_service=fake_reference_service,
        )


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_rejected():
    """
    Add in a test for when a robot rejects a request to create an enhancement against a
    reference.
    """


@pytest.mark.asyncio
async def test_get_enhancement_request_happy_path(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()
    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=uuid.uuid4(),
        enhancement_type=EnhancementType.ANNOTATION,
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = RobotService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert returned_enhancement_request == existing_enhancement_request


@pytest.mark.asyncio
async def test_get_enhancement_request_doesnt_exist(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = RobotService(uow)

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert not returned_enhancement_request


@pytest.mark.asyncio
async def test_create_reference_enhancement_happy_path(fake_repository, fake_uow):
    """
    Add in a test for when a we create a reference enhancement off the back
    of a robot callback.
    """
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=reference_id,
        enhancement_type=EnhancementType.ANNOTATION,
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    enhancement_data = {
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

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_repository(),
        enhancements=fake_repository(),
    )

    service = RobotService(uow)
    fake_reference_service = AsyncMock()
    fake_reference_service.add_enhancement.return_value = Enhancement(
        reference_id=reference_id, **enhancement_data
    )

    enhancement = await service.create_reference_enhancement(
        enhancement_request_id=enhancement_request_id,
        enhancement=EnhancementCreate(**enhancement_data),
        reference_service=fake_reference_service,
    )

    enhancement_request = await service.get_enhancement_request(enhancement_request_id)

    assert enhancement.enhancement_type == enhancement_request.enhancement_type
    assert enhancement_request.request_status == EnhancementRequestStatus.COMPLETED


@pytest.mark.asyncio
async def test_create_reference_enhancement_types_dont_match(fake_repository, fake_uow):
    """
    Add in a test for when a we create a reference enhancement off the back
    of a robot callback.
    """
    enhancement_request_id = uuid.uuid4()
    reference_id = uuid.uuid4()

    existing_enhancement_request = EnhancementRequest(
        id=enhancement_request_id,
        reference_id=reference_id,
        enhancement_type=EnhancementType.BIBLIOGRAPHIC,
        request_status=EnhancementRequestStatus.ACCEPTED,
    )

    enhancement_data = {
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

    fake_enhancement_requests = fake_repository([existing_enhancement_request])
    uow = fake_uow(
        enhancement_requests=fake_enhancement_requests,
        references=fake_repository(),
        enhancements=fake_repository(),
    )

    service = RobotService(uow)
    fake_reference_service = AsyncMock()
    fake_reference_service.add_enhancement.return_value = Enhancement(
        reference_id=reference_id, **enhancement_data
    )

    with pytest.raises(RuntimeError):
        await service.create_reference_enhancement(
            enhancement_request_id=enhancement_request_id,
            enhancement=EnhancementCreate(**enhancement_data),
            reference_service=fake_reference_service,
        )
