import time
import uuid

import destiny_sdk
import httpx
import pytest
from fastapi import status

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.models.models import (
    BatchEnhancementRequest,
)
from app.domain.robots.models.models import Robot
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher


@pytest.fixture
def frozen_time(monkeypatch):
    def frozen_timestamp():
        return 12345453.32423

    monkeypatch.setattr(time, "time", frozen_timestamp)


@pytest.fixture
def robot():
    return Robot(
        id=uuid.uuid4(),
        base_url="http://www.theres-a-robot-here.com/",
        client_secret="secret-secret",
        description="it's a robot",
        name="robot",
        owner="owner",
    )


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_happy_path(
    httpx_mock,
    frozen_time,  # noqa: ARG001
    robot,
):
    enhancement_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=robot.id,
        enhancement_parameters={},
    )

    robot_request = destiny_sdk.robots.BatchRobotRequest(
        id=enhancement_request.id,
        reference_storage_url="https://fake-reference-storage-url.org",
        result_storage_url="https://fake-result-storage-url.org",
        extra_fields=enhancement_request.enhancement_parameters,
    )

    expected_signature = destiny_sdk.client.create_signature(
        secret_key=robot.client_secret.get_secret_value(),
        request_body=robot_request.model_dump_json().encode(),
        client_id=robot.id,
        timestamp=time.time(),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(robot.base_url) + "batch/",
        status_code=status.HTTP_202_ACCEPTED,
        match_headers={
            "Authorization": f"Signature {expected_signature}",
            "X-Client-Id": f"{robot.id}",
            "X-Request-Timestamp": f"{time.time()}",
        },
    )

    dispatcher = RobotRequestDispatcher()

    await dispatcher.send_enhancement_request_to_robot(
        endpoint="/batch/", robot=robot, robot_request=robot_request
    )

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_request_error(httpx_mock, robot):
    # Mock a connection error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    enhancement_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=robot.id,
        enhancement_parameters={},
    )

    robot_request = destiny_sdk.robots.BatchRobotRequest(
        id=enhancement_request.id,
        reference_storage_url="https://fake-reference-storage-url.org",
        result_storage_url="https://fake-result-storage-url.org",
        extra_fields=enhancement_request.enhancement_parameters,
    )

    dispatcher = RobotRequestDispatcher()

    with pytest.raises(RobotUnreachableError):
        await dispatcher.send_enhancement_request_to_robot(
            endpoint="/batch/", robot=robot, robot_request=robot_request
        )


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_503_response(httpx_mock, robot):
    # Mock a robot that is unavailable
    httpx_mock.add_response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    enhancement_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=robot.id,
        enhancement_parameters={},
    )

    robot_request = destiny_sdk.robots.BatchRobotRequest(
        id=enhancement_request.id,
        reference_storage_url="https://fake-reference-storage-url.org",
        result_storage_url="https://fake-result-storage-url.org",
        extra_fields=enhancement_request.enhancement_parameters,
    )

    dispatcher = RobotRequestDispatcher()

    with pytest.raises(RobotUnreachableError):
        await dispatcher.send_enhancement_request_to_robot(
            endpoint="/batch/", robot=robot, robot_request=robot_request
        )


@pytest.mark.asyncio
async def test_send_enhancement_request_to_robot_400_response(httpx_mock, robot):
    # Mock a robot that is unavailable
    httpx_mock.add_response(
        status_code=status.HTTP_400_BAD_REQUEST, json={"message": "bad request"}
    )

    enhancement_request = BatchEnhancementRequest(
        id=uuid.uuid4(),
        reference_ids=[uuid.uuid4()],
        robot_id=robot.id,
        enhancement_parameters={},
    )

    robot_request = destiny_sdk.robots.BatchRobotRequest(
        id=enhancement_request.id,
        reference_storage_url="https://fake-reference-storage-url.org",
        result_storage_url="https://fake-result-storage-url.org",
        extra_fields=enhancement_request.enhancement_parameters,
    )

    dispatcher = RobotRequestDispatcher()

    with pytest.raises(RobotEnhancementError):
        await dispatcher.send_enhancement_request_to_robot(
            endpoint="/batch/", robot=robot, robot_request=robot_request
        )
