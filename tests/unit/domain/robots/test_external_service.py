import uuid

import destiny_sdk
import httpx
import pytest
from destiny_sdk.visibility import Visibility
from fastapi import status
from pydantic import HttpUrl

from app.core.auth import create_signature
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
FAKE_ROBOT_TOKEN = "access_token"

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
async def test_send_enhancement_request_to_robot_happy_path(httpx_mock):
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

    robot_request = destiny_sdk.robots.RobotRequest(
        id=enhancement_request.id,
        reference=destiny_sdk.references.Reference(**reference.model_dump()),
        extra_fields=enhancement_request.enhancement_parameters,
    )

    expected_signature = create_signature(
        secret_key=KNOWN_ROBOTS[0].communication_secret_name,
        request_body=robot_request.model_dump_json().encode(),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(ROBOT_URL) + "single/",
        status_code=status.HTTP_202_ACCEPTED,
        match_headers={"Authorization": f"Signature {expected_signature}"},
    )

    await service.send_enhancement_request_to_robot(
        endpoint="/single/", robot=KNOWN_ROBOTS[0], robot_request=robot_request
    )

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_request_error(httpx_mock):
    # Mock a connection error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    robot_request = destiny_sdk.robots.RobotRequest(
        id=enhancement_request.id,
        reference=destiny_sdk.references.Reference(**reference.model_dump()),
        extra_fields=enhancement_request.enhancement_parameters,
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotUnreachableError):
        await service.send_enhancement_request_to_robot(
            endpoint="/single/", robot=KNOWN_ROBOTS[0], robot_request=robot_request
        )


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_503_response(httpx_mock):
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

    robot_request = destiny_sdk.robots.RobotRequest(
        id=enhancement_request.id,
        reference=destiny_sdk.references.Reference(**reference.model_dump()),
        extra_fields=enhancement_request.enhancement_parameters,
    )

    with pytest.raises(RobotUnreachableError):
        await service.send_enhancement_request_to_robot(
            endpoint="/single/", robot=KNOWN_ROBOTS[0], robot_request=robot_request
        )


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_400_response(httpx_mock):
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

    robot_request = destiny_sdk.robots.RobotRequest(
        id=enhancement_request.id,
        reference=destiny_sdk.references.Reference(**reference.model_dump()),
        extra_fields=enhancement_request.enhancement_parameters,
    )

    service = RobotCommunicationService(
        robots=RobotService(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotEnhancementError):
        await service.send_enhancement_request_to_robot(
            endpoint="/single/", robot=KNOWN_ROBOTS[0], robot_request=robot_request
        )
