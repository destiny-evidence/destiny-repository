"""Tests client authentication"""

import random
import string
import uuid

from destiny_sdk.client import Client
from destiny_sdk.client_auth import AccessTokenAuthentication
from destiny_sdk.robots import EnhancementRequestRead, RobotError, RobotResult
from pytest_httpx import HTTPXMock


def test_verify_token_send_as_header(httpx_mock: HTTPXMock) -> None:
    """Test that request is authorizes with provided token."""
    fake_token = "".join(random.choice(string.ascii_letters) for _ in range(30))  # noqa: S311

    fake_destiny_repository_url = "https://www.destiny-repository-lives-here.co.au"
    httpx_mock.add_response(
        url=fake_destiny_repository_url + "/robot/enhancement/single/",
        method="POST",
        headers={"Authorization": f"Bearer {fake_token}"},
        json=EnhancementRequestRead(
            reference_id=uuid.uuid4(),
            id=uuid.uuid4(),
            robot_id=uuid.uuid4(),
            request_status="completed",
        ).model_dump(mode="json"),
    )

    fake_auth_method = AccessTokenAuthentication(access_token=fake_token)

    fake_robot_result = RobotResult(
        request_id=uuid.uuid4(), error=RobotError(message="I can't fulfil this request")
    )

    Client(
        base_url=fake_destiny_repository_url, auth_method=fake_auth_method
    ).send_robot_result(
        robot_result=fake_robot_result,
    )

    callback_request = httpx_mock.get_requests()
    assert len(callback_request) == 1
