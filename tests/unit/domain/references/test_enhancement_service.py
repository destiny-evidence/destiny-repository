import uuid

import httpx
import pytest
from fastapi import status
from pydantic import HttpUrl

from app.core.exceptions import (
    NotFoundError,
    RobotUnreachableError,
    SQLNotFoundError,
    WrongReferenceError,
)
from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    Reference,
    Visibility,
)
from app.domain.robots import Robots

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
async def test_request_enhancement_from_robot_request_error(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a connection error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    robot_url = "http://www.theres-a-robot-here.com/"
    robot_id = uuid.uuid4()

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=robot_id,
        enhancement_parameters={},
    )

    fake_enhancement_requests = fake_repository(init_entries=[enhancement_request])

    service = EnhancementService(
        fake_uow(enhancement_requests=fake_enhancement_requests),
        robots=Robots(known_robots={robot_id: HttpUrl(robot_url)}),
    )

    with pytest.raises(RobotUnreachableError):
        await service.request_enhancement_from_robot(
            robot_url=robot_url,
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_happy_path(
    fake_repository, fake_uow, httpx_mock
):
    # Mock the robot
    robot_url = "http://www.theres-a-robot-here.com/"
    robot_id = uuid.uuid4()
    httpx_mock.add_response(
        method="POST", url=robot_url, status_code=status.HTTP_202_ACCEPTED
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

    service = EnhancementService(
        uow, robots=Robots(known_robots={robot_id: HttpUrl(robot_url)})
    )

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=robot_id, enhancement_parameters={}
    )

    enhancement_request = await service.request_reference_enhancement(
        enhancement_request=received_enhancement_request
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.ACCEPTED


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_request_rejected(
    fake_uow, fake_repository, httpx_mock
):
    """
    A robot rejects a request to create an enhancement against a reference.
    """
    # Mock the robot
    robot_url = "http://www.theres-a-robot-here.com/"
    robot_id = uuid.uuid4()
    httpx_mock.add_response(
        method="POST",
        url=robot_url,
        status_code=status.HTTP_418_IM_A_TEAPOT,
        json={"message": "broken"},
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

    service = EnhancementService(
        uow, robots=Robots(known_robots={robot_id: HttpUrl(robot_url)})
    )

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=robot_id, enhancement_parameters={}
    )

    enhancement_request = await service.request_reference_enhancement(
        enhancement_request=received_enhancement_request,
    )

    stored_request = fake_enhancement_requests.get_first_record()

    assert hasattr(enhancement_request, "id")
    assert enhancement_request == stored_request
    assert enhancement_request.request_status == EnhancementRequestStatus.REJECTED
    assert enhancement_request.error == "broken"


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_nonexistent_reference(
    fake_uow, fake_repository
):
    """
    Enhancement requested against nonexistent reference
    """
    robot_id = uuid.uuid4()
    robot_url = "http://www.theres-a-robot-here.com/"

    unknown_reference_id = uuid.uuid4()

    uow = fake_uow(enhancement_requests=fake_repository(), references=fake_repository())

    service = EnhancementService(
        uow, robots=Robots(known_robots={robot_id: HttpUrl(robot_url)})
    )

    service = EnhancementService(uow, robots=Robots({}))

    received_enhancement_request = EnhancementRequest(
        reference_id=unknown_reference_id, robot_id=robot_id, enhancement_parameters={}
    )

    with pytest.raises(SQLNotFoundError):
        await service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
        )


@pytest.mark.asyncio
async def test_trigger_reference_enhancement_nonexistent_robot(
    fake_uow, fake_repository
):
    """
    Enhancement requested against a robot that does not exist.
    """
    unknown_robot_id = uuid.uuid4()

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

    service = EnhancementService(uow, robots=Robots({}))

    received_enhancement_request = EnhancementRequest(
        reference_id=reference_id, robot_id=unknown_robot_id, enhancement_parameters={}
    )

    with pytest.raises(NotFoundError):
        await service.request_reference_enhancement(
            enhancement_request=received_enhancement_request,
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
    service = EnhancementService(uow, robots=Robots({}))

    returned_enhancement_request = await service.get_enhancement_request(
        enhancement_request_id
    )

    assert returned_enhancement_request == existing_enhancement_request


@pytest.mark.asyncio
async def test_get_enhancement_request_doesnt_exist(fake_repository, fake_uow):
    enhancement_request_id = uuid.uuid4()

    fake_enhancement_requests = fake_repository()
    uow = fake_uow(enhancement_requests=fake_enhancement_requests)
    service = EnhancementService(uow, robots=Robots({}))

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

    service = EnhancementService(uow, robots=Robots({}))

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

    service = EnhancementService(uow, robots=Robots({}))

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

    service = EnhancementService(uow, robots=Robots({}))

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

    service = EnhancementService(uow, robots=Robots({}))

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
    service = EnhancementService(uow, robots=Robots({}))

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
    service = EnhancementService(uow, robots=Robots({}))

    with pytest.raises(SQLNotFoundError):
        await service.mark_enhancement_request_failed(
            enhancement_request_id=missing_enhancement_request_id, error="it broke"
        )
