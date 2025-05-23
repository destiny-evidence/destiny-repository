"""
Test batch enhancements with robots.

Consider reducing number of assertions, particularly string-sensitive, once
unit and integration test coverage is sound.
"""

import os

import destiny_sdk
import httpx
import pytest
from sqlalchemy import create_engine

toy_robot_id = os.environ["TOY_ROBOT_ID"]

db_url = os.environ["DB_URL"]
minio_url = os.environ["MINIO_URL"]
repo_url = os.environ["REPO_URL"]
engine = create_engine(db_url)


# e2e tests are ordered for easier seeding of downstream tests
@pytest.mark.order(2)
def test_complete_batch_enhancement_workflow():
    """Test complete batch enhancement workflow, happy-ish path."""
    with (
        httpx.Client(base_url=repo_url) as repo_client,
    ):
        # 1: Create a batch enhancement request against the repo
        # 1a: get a list of references
        # This will eventually be a search function on the repo :)
        reference_ids = []
        for identifier, identifier_type in (
            ("10.1234/sampledoi", "doi"),
            ("123456", "pm_id"),
            ("W123456789", "open_alex"),
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
        assert len(reference_ids) == 3
        response = repo_client.post(
            "/enhancements/batch/",
            json=destiny_sdk.robots.BatchEnhancementRequestIn(
                robot_id=toy_robot_id, reference_ids=reference_ids
            ).model_dump_json(),
        )
        assert response.status_code == 201
        batch = response.json()
        batch_id = batch["id"]
        assert batch["status"] == "received"

        while True:
            # Wait for completion
            response = repo_client.get(
                f"/enhancements/batch/{batch_id}/",
            )
            assert response.status_code == 200
            if (request := response.json())["status"] not in (
                "received",
                "accepted",
                "processed",
            ):
                break

        assert request["status"] == "completed"
