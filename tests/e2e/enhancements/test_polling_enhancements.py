"""Test polling pending enhancements."""

import os
import time

import destiny_sdk
import httpx
import pytest

toy_robot_url = os.environ["TOY_ROBOT_URL"]
repo_url = os.environ["REPO_URL"]


@pytest.mark.order(3)
def test_polling_enhancement_requests():
    """Test the happy path for a robot polling for enhancement requests."""
    with httpx.Client(base_url=repo_url) as repo_client:
        # First, create a robot
        robot_in = {
            "name": "Polling Test Robot",
            "base_url": toy_robot_url,
            "description": "A robot for testing the polling endpoint.",
            "owner": "Test Suite",
        }
        response = repo_client.post("/robots/", json=robot_in)
        assert response.status_code == 201
        robot = response.json()
        robot_id = robot["id"]

        # Then, get some references
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

        # Create a batch enhancement request to generate pending enhancements
        batch_request_in = destiny_sdk.robots.BatchEnhancementRequestIn(
            robot_id=robot_id, reference_ids=reference_ids
        )
        response = repo_client.post(
            "/enhancement-requests/batch-requests/",
            json=batch_request_in.model_dump(mode="json"),
        )
        assert response.status_code == 202
        batch = response.json()
        batch_id = batch["id"]

        # Wait for the batch request to be processed and pending enhancements created
        while True:
            time.sleep(1)
            response = repo_client.get(
                f"/enhancement-requests/batch-requests/{batch_id}/",
            )
            assert response.status_code == 200
            if (response.json())["request_status"] not in (
                "received",
                "accepted",
                "importing",
            ):
                break

        # Now, poll the endpoint as the robot
        for _ in range(2):
            response = repo_client.get(
                "/enhancement-requests/",
                params={"robot_id": robot_id, "limit": 2},
            )
            assert response.status_code == 200

            result = destiny_sdk.robots.BatchRobotRequest.model_validate(
                response.json()
            )
            reference_storage_file = httpx.get(str(result.reference_storage_url))

            assert reference_storage_file.status_code == 200
            reference_lines = reference_storage_file.text.splitlines()
            assert len(reference_lines) == 2
            for line in reference_lines:
                reference = destiny_sdk.references.Reference.model_validate_json(line)
                assert str(reference.id) in reference_ids

        # Poll again, should get an empty response
        response = repo_client.get(
            "/enhancement-requests/", params={"robot_id": robot_id, "limit": 2}
        )
        assert response.status_code == 204
