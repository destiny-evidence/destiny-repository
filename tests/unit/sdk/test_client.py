"""Tests client authentication"""

import uuid

from destiny_sdk.client import Client, create_signature
from destiny_sdk.robots import EnhancementRequestRead, RobotError, RobotResult
from pytest_httpx import HTTPXMock


def test_verify_signature_sent_as_header(httpx_mock: HTTPXMock) -> None:
    """Test that request is authorized with a signature."""
    fake_secret_key = "asdfhjgji94523q0uflsjf349wjilsfjd9q23"
    fake_robot_id = uuid.uuid4()
    fake_destiny_repository_url = "https://www.destiny-repository-lives-here.co.au"

    request_body = EnhancementRequestRead(
        reference_id=uuid.uuid4(),
        id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status="completed",
    )

    expected_signature = create_signature(
        fake_secret_key, request_body.model_dump_json().encode()
    )

    httpx_mock.add_response(
        url=fake_destiny_repository_url + "/robot/enhancement/single/",
        method="POST",
        headers={"Authorization": f"Signature {expected_signature}"},
        json=request_body.model_dump(mode="json"),
    )

    fake_robot_result = RobotResult(
        request_id=uuid.uuid4(), error=RobotError(message="I can't fulfil this request")
    )

    Client(
        base_url=fake_destiny_repository_url,
        secret_key=fake_secret_key,
        client_id=fake_robot_id,
    ).send_robot_result(
        robot_result=fake_robot_result,
    )

    callback_request = httpx_mock.get_requests()
    assert len(callback_request) == 1
