"""Tests client authentication"""

import time
import uuid

import pytest
from destiny_sdk.client import Client, create_signature
from destiny_sdk.robots import EnhancementRequestRead, RobotError, RobotResult
from pytest_httpx import HTTPXMock


@pytest.fixture
def frozen_time(monkeypatch):
    def frozen_timestamp():
        return 12345453.32423

    monkeypatch.setattr(time, "time", frozen_timestamp)


def test_verify_hmac_headers_sent(httpx_mock: HTTPXMock, frozen_time) -> None:  # noqa: ARG001
    """Test that request is authorized with a signature."""
    fake_secret_key = "asdfhjgji94523q0uflsjf349wjilsfjd9q23"
    fake_robot_id = uuid.uuid4()
    fake_destiny_repository_url = "https://www.destiny-repository-lives-here.co.au/v1"

    fake_robot_result = RobotResult(
        request_id=uuid.uuid4(), error=RobotError(message="Cannot process this batch")
    )

    expected_response_body = EnhancementRequestRead(
        reference_ids=[uuid.uuid4()],
        id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        request_status="failed",
    )

    expected_signature = create_signature(
        secret_key=fake_secret_key,
        request_body=fake_robot_result.model_dump_json().encode(),
        client_id=fake_robot_id,
        timestamp=time.time(),
    )

    httpx_mock.add_response(
        url=fake_destiny_repository_url
        + "/enhancement-requests/"
        + f"{fake_robot_result.request_id}/results/",
        method="POST",
        match_headers={
            "Authorization": f"Signature {expected_signature}",
            "X-Client-Id": f"{fake_robot_id}",
            "X-Request-Timestamp": f"{time.time()}",
        },
        json=expected_response_body.model_dump(mode="json"),
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
