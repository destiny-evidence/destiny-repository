"""Test polling pending enhancements."""

import os
import time

import httpx
import pytest
from destiny_sdk.enhancements import BibliographicMetadataEnhancement, Enhancement
from destiny_sdk.references import Reference
from destiny_sdk.robots import (
    EnhancementRequestIn,
    EnhancementRequestStatus,
    RobotEnhancementBatch,
    RobotResult,
)
from destiny_sdk.visibility import Visibility

toy_robot_url = os.environ["TOY_ROBOT_URL"]
repo_url = os.environ["REPO_URL"]


def _create_robot(repo_client: httpx.Client) -> str:
    """Create a test robot and return robot ID."""
    robot_in = {
        "name": "Polling Test Robot",
        "base_url": toy_robot_url,
        "description": "A robot for testing the polling endpoint.",
        "owner": "Test Suite",
    }
    response = repo_client.post("/robots/", json=robot_in)
    assert response.status_code == 201
    robot = response.json()
    return robot["id"]


def _get_test_references(repo_client: httpx.Client) -> list[str]:
    """Get test references and return their IDs."""
    reference_ids = []
    for identifier, identifier_type in (
        ("10.1234/sampledoi", "doi"),
        ("123456", "pm_id"),
        ("W123456789", "open_alex"),
        ("W123456790", "open_alex"),
    ):
        response = repo_client.get(
            "/references/",
            params={
                "identifier": identifier,
                "identifier_type": identifier_type,
            },
        )
        assert response.status_code == 200
        reference_ids.append(response.json()["id"])
    assert len(reference_ids) == 4
    return reference_ids


def _create_enhancement_request(
    repo_client: httpx.Client, robot_id: str, reference_ids: list[str]
) -> str:
    """Create an enhancement request and return request ID."""
    request_in = EnhancementRequestIn(robot_id=robot_id, reference_ids=reference_ids)
    response = repo_client.post(
        "/enhancement-requests/",
        json=request_in.model_dump(mode="json"),
    )
    assert response.status_code == 202
    request_out = response.json()
    return request_out["id"]


def _poll_robot_batches(
    repo_client: httpx.Client,
    robot_id: str,
    reference_ids: list[str],
    request_id: str,
) -> tuple[list[str], list[list[str]], list[RobotEnhancementBatch]]:
    """Poll for robot enhancement batches and return batch data."""
    robot_enhancement_batch_ids = []
    batch_references = []
    robot_requests = []

    for _ in range(2):
        response = repo_client.post(
            "/robot-enhancement-batch/",
            params={"robot_id": robot_id, "limit": 2},
        )
        assert response.status_code == 200

        result = RobotEnhancementBatch.model_validate(response.json())
        robot_enhancement_batch_ids.append(str(result.id))
        robot_requests.append(result)

        reference_storage_file = httpx.get(str(result.reference_storage_url))
        assert reference_storage_file.status_code == 200
        reference_lines = reference_storage_file.text.splitlines()
        assert len(reference_lines) == 2

        # Store references for this batch for creating results
        batch_ref_ids = []
        for line in reference_lines:
            reference = Reference.model_validate_json(line)
            assert str(reference.id) in reference_ids
            batch_ref_ids.append(str(reference.id))
        batch_references.append(batch_ref_ids)

        # Verify status changes to processing
        response = repo_client.get(f"/enhancement-requests/{request_id}/")
        assert response.status_code == 200
        request_status = response.json()["request_status"]
        assert request_status == EnhancementRequestStatus.PROCESSING

    return robot_enhancement_batch_ids, batch_references, robot_requests


def _submit_robot_results(
    repo_client: httpx.Client,
    robot_enhancement_batch_ids: list[str],
    batch_references: list[list[str]],
    robot_requests: list[RobotEnhancementBatch],
) -> None:
    """Submit robot enhancement batch results."""
    for i, (batch_id, robot_request) in enumerate(
        zip(robot_enhancement_batch_ids, robot_requests, strict=True)
    ):
        result_entries = []

        for ref_id in batch_references[i]:
            enhancement = Enhancement(
                reference_id=ref_id,
                source="Test Robot Enhancement",
                visibility=Visibility.PUBLIC,
                robot_version="1.0.0",
                content=BibliographicMetadataEnhancement(
                    title="Enhanced Title from Test Robot",
                    publisher="Test Publisher",
                ),
            )
            result_entries.append(enhancement.to_jsonl())

        # Upload result file to the provided result storage URL
        result_content = "\n".join(result_entries)
        upload_response = httpx.put(
            str(robot_request.result_storage_url),
            content=result_content.encode("utf-8"),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload_response.status_code == 200

        robot_result = RobotResult(request_id=batch_id, error=None)

        response = repo_client.post(
            f"/robot-enhancement-batch/{batch_id}/results/",
            json=robot_result.model_dump(mode="json"),
        )
        assert response.status_code == 202


@pytest.mark.order(3)
def test_polling_pending_enhancements():
    """Test the happy path for a robot polling for pending enhancements."""
    with httpx.Client(base_url=repo_url) as repo_client:
        robot_id = _create_robot(repo_client)
        reference_ids = _get_test_references(repo_client)

        # Create enhancement request and verify initial status
        request_id = _create_enhancement_request(repo_client, robot_id, reference_ids)
        response = repo_client.get(f"/enhancement-requests/{request_id}/")
        assert response.status_code == 200
        request_status = response.json()["request_status"]
        assert request_status == EnhancementRequestStatus.RECEIVED

        batch_ids, batch_refs, robot_requests = _poll_robot_batches(
            repo_client, robot_id, reference_ids, request_id
        )

        # Verify no more batches available
        response = repo_client.post(
            "/robot-enhancement-batch/", params={"robot_id": robot_id, "limit": 2}
        )
        assert response.status_code == 204

        _submit_robot_results(repo_client, batch_ids, batch_refs, robot_requests)

        retries = 0
        max_retries = 3
        while retries < max_retries:
            time.sleep(1)
            response = repo_client.get(f"/enhancement-requests/{request_id}/")
            assert response.status_code == 200
            response_status = response.json()["request_status"]
            if response_status not in (
                EnhancementRequestStatus.PROCESSING.value,
                EnhancementRequestStatus.IMPORTING.value,
                EnhancementRequestStatus.INDEXING.value,
            ):
                break
            retries += 1

        assert response_status == EnhancementRequestStatus.COMPLETED.value
