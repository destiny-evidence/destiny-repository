"""Tests client authentication"""

import time
import uuid

import pytest
from destiny_sdk.client import Client, create_signature
from destiny_sdk.robots import (
    RobotEnhancementBatchRead,
    RobotEnhancementBatchResult,
    RobotError,
)
from pydantic import HttpUrl
from pytest_httpx import HTTPXMock


@pytest.fixture
def frozen_time(monkeypatch):
    def frozen_timestamp():
        return 12345453.32423

    monkeypatch.setattr(time, "time", frozen_timestamp)


def test_verify_hmac_headers_sent(
    httpx_mock: HTTPXMock,
    frozen_time,  # noqa: ARG001
) -> None:
    """Test that robot enhancement batch result request is authorized."""
    fake_secret_key = "asdfhjgji94523q0uflsjf349wjilsfjd9q23"
    fake_robot_id = uuid.uuid4()
    fake_destiny_repository_url = "https://www.destiny-repository-lives-here.co.au/v1"

    fake_batch_result = RobotEnhancementBatchResult(
        request_id=uuid.uuid4(), error=RobotError(message="Cannot process this batch")
    )

    expected_response_body = RobotEnhancementBatchRead(
        id=uuid.uuid4(),
        robot_id=uuid.uuid4(),
        error="Cannot process this batch",
    )

    expected_signature = create_signature(
        secret_key=fake_secret_key,
        request_body=fake_batch_result.model_dump_json().encode(),
        client_id=fake_robot_id,
        timestamp=time.time(),
    )

    httpx_mock.add_response(
        url=fake_destiny_repository_url
        + "/robot-enhancement-batches/"
        + f"{fake_batch_result.request_id}/results/",
        method="POST",
        match_headers={
            "Authorization": f"Signature {expected_signature}",
            "X-Client-Id": f"{fake_robot_id}",
            "X-Request-Timestamp": f"{time.time()}",
        },
        json=expected_response_body.model_dump(mode="json"),
    )

    Client(
        base_url=HttpUrl(fake_destiny_repository_url),
        secret_key=fake_secret_key,
        client_id=fake_robot_id,
    ).send_robot_enhancement_batch_result(
        robot_enhancement_batch_result=fake_batch_result,
    )

    callback_request = httpx_mock.get_requests()
    assert len(callback_request) == 1
