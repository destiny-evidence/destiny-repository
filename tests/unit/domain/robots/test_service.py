import uuid

import httpx
import pytest
from destiny_sdk.visibility import Visibility
from fastapi import status
from pydantic import HttpUrl

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.models.models import (
    EnhancementRequest,
    Reference,
)
from app.domain.robots.external_service import RobotCommunicationService
from app.domain.robots.models import RobotConfig
from app.domain.robots.service import RobotService

ROBOT_ID = uuid.uuid4()
ROBOT_URL = HttpUrl("http://www.theres-a-robot-here.com/")
FAKE_ROBOT_TOKEN = "access_token"  # noqa: S105

KNOWN_ROBOTS = [
    RobotConfig(
        robot_id=ROBOT_ID,
        robot_url=ROBOT_URL,
        dependent_enhancements=[],
        dependent_identifiers=[],
        communication_secret_name="secret-secret",
    ),
]


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_happy_path(httpx_mock):
    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        enhancement_parameters={},
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(ROBOT_URL) + "single/",
        status_code=status.HTTP_202_ACCEPTED,
    )

    await service.request_enhancement_from_robot(
        robot_config=KNOWN_ROBOTS[0],
        enhancement_request=enhancement_request,
        reference=reference,
    )

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_request_error(httpx_mock):
    # Mock a connection error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotUnreachableError):
        await service.request_enhancement_from_robot(
            robot_config=KNOWN_ROBOTS[0],
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_503_response(httpx_mock):
    # Mock a robot that is unavailable
    httpx_mock.add_response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotUnreachableError):
        await service.request_enhancement_from_robot(
            robot_config=KNOWN_ROBOTS[0],
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_400_response(httpx_mock):
    # Mock a robot that is unavailable
    httpx_mock.add_response(
        status_code=status.HTTP_400_BAD_REQUEST, json={"message": "bad request"}
    )

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotEnhancementError):
        await service.request_enhancement_from_robot(
            robot_config=KNOWN_ROBOTS[0],
            enhancement_request=enhancement_request,
            reference=reference,
        )
