"""
Test batch enhancements with robots.

Consider reducing number of assertions, particularly string-sensitive, once
unit and integration test coverage is sound.
"""

import os
import time

import destiny_sdk
import httpx
import pytest
from sqlalchemy import create_engine, text

toy_robot_id = os.environ["TOY_ROBOT_ID"]

db_url = os.environ["DB_URL"]
minio_url = os.environ["MINIO_URL"]
repo_url = os.environ["REPO_URL"]
engine = create_engine(db_url)


# e2e tests are ordered for easier seeding of downstream tests
@pytest.mark.order(2)
# Remove the below if you want to run e2e tests locally with the toy robot.
@pytest.mark.skip(reason="Skipped in GH action, requires toy robot access.")
def test_complete_batch_enhancement_workflow():
    """Test complete batch enhancement workflow, happy-ish path."""
    with (
        httpx.Client(base_url=repo_url) as repo_client,
    ):
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
            "/references/enhancement/batch/",
            json=destiny_sdk.robots.BatchEnhancementRequestIn(
                robot_id=toy_robot_id, reference_ids=reference_ids
            ).model_dump(mode="json"),
        )
        assert response.status_code == 202
        batch = response.json()
        batch_id = batch["id"]
        assert batch["request_status"] == "received"

        while True:
            time.sleep(1)
            # Wait for completion
            response = repo_client.get(
                f"/references/enhancement/batch/request/{batch_id}/",
            )
            assert response.status_code == 200
            if (request := response.json())["request_status"] not in (
                "received",
                "accepted",
                "importing",
            ):
                break

        assert request["request_status"] == "completed"
        result = destiny_sdk.robots.BatchEnhancementRequestRead.model_validate(request)
        validation_file = httpx.get(str(result.validation_result_url))
        for line in validation_file.text.splitlines():
            entry = (
                destiny_sdk.robots.BatchRobotResultValidationEntry.model_validate_json(
                    line
                )
            )
            assert str(entry.reference_id) in reference_ids
            assert not entry.error
        reference_data_file = httpx.get(str(result.reference_data_url))
        for line in reference_data_file.text.splitlines():
            reference = destiny_sdk.references.Reference.model_validate_json(line)
            assert str(reference.id) in reference_ids
            # Check we only got enhancements we're dependent on
            dependent_enhancements = {"abstract", "annotation"}
            dependent_identifiers = {"doi", "pm_id"}
            assert not (
                {e.content.enhancement_type for e in reference.enhancements}
                - dependent_enhancements
            )
            assert not (
                {i.identifier_type for i in reference.identifiers}
                - dependent_identifiers
            )

    # Finally check we got some toys themselves
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"""
            SELECT * FROM reference r
            LEFT JOIN enhancement e ON r.id = e.reference_id
            WHERE reference_id IN {tuple(reference_ids)}
            """  # noqa: S608
            ),
        )
        toy_found = dict.fromkeys(reference_ids, False)
        for row in result:
            assert str(row.reference_id) in reference_ids
            if row.enhancement_type == "annotation" and row.source == "Toy Robot":
                toy_found[str(row.reference_id)] = True

        if not all(toy_found.values()):
            msg = "Expected toy robot enhancement not found in reference."
            raise AssertionError(msg)
