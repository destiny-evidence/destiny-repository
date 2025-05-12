import uuid

import httpx
import pytest
from destiny_sdk.visibility import Visibility
from fastapi import status
from pydantic import HttpUrl

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.models.models import EnhancementRequest, Reference
from app.domain.robots.models import Robots
from app.domain.robots.service import RobotService


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_happy_path(fake_uow, httpx_mock):
    robot_id = uuid.uuid4()
    robot_url = HttpUrl("http://www.theres-a-robot-here.com/")

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        enhancement_parameters={},
    )

    service = RobotService(
        fake_uow(enhancement_requests=enhancement_request),
        robots=Robots(known_robots={robot_id: robot_url}),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(robot_url),
        status_code=status.HTTP_202_ACCEPTED,
    )

    await service.request_enhancement_from_robot(
        robot_url=robot_url,
        enhancement_request=enhancement_request,
        reference=reference,
    )

    assert len(httpx_mock.get_requests()) == 1


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

    service = RobotService(
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
async def test_request_enhancement_from_robot_503_response(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a robot that is unavailable
    httpx_mock.add_response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

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

    service = RobotService(
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
async def test_request_enhancement_from_robot_400_response(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a robot that is unavailable
    httpx_mock.add_response(
        status_code=status.HTTP_400_BAD_REQUEST, json={"message": "bad request"}
    )

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

    service = RobotService(
        fake_uow(enhancement_requests=fake_enhancement_requests),
        robots=Robots(known_robots={robot_id: HttpUrl(robot_url)}),
    )

    with pytest.raises(RobotEnhancementError):
        await service.request_enhancement_from_robot(
            robot_url=robot_url,
            enhancement_request=enhancement_request,
            reference=reference,
        )
