"""
Test batch enhancements with robots.

This test sends

Consider reducing number of assertions, particularly string-sensitive, once
unit and integration test coverage is sound.
"""

import os
import time

import destiny_sdk
import httpx
import pytest
from elasticsearch import Elasticsearch
from sqlalchemy import create_engine, text

toy_robot_url = os.environ["TOY_ROBOT_URL"]

db_url = os.environ["DB_URL"]
minio_url = os.environ["MINIO_URL"]
repo_url = os.environ["REPO_URL"]
engine = create_engine(db_url)


# e2e tests are ordered for easier seeding of downstream tests
@pytest.mark.order(2)
# Remove the below if you want to run e2e tests locally with the toy robot.
def test_complete_batch_enhancement_workflow():  # noqa: C901, PLR0912, PLR0915
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

        # Add a second toy robot
        # We do this so that we can test automatic robots on enhancements:
        # 1. request batch enhancement on robot number 2
        # 2. robot number 2 imports the enhancements
        # 3. repo sends automatic request to robot number 1
        # 4. robot number 1 imports the enhancements
        # 5. repo considers sending automatic request to robot number 1,
        #    notices that request_robot == automatic_robot, stops
        response = repo_client.post(
            "/robot/",
            json={
                "name": "Toy Robot 2 but really it's just Toy Robot 1",
                "base_url": toy_robot_url,
                "description": "Provides toy annotation enhancements",
                "owner": "Future Evidence Foundation",
            },
        )
        assert response.status_code == 201
        toy_robot_id = response.json()["id"]

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

        # Check the ad-hoc request
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

        # Check the automatic requests from the import
        with engine.connect() as conn:
            result = list(
                conn.execute(
                    text(
                        f"""
                    SELECT id FROM batch_enhancement_request
                    WHERE robot_id <> '{toy_robot_id}';
                    """  # noqa: S608
                    ),
                ).scalars()
            )
            assert len(result) == 2
            import_auto_request_found = False
            batch_auto_request_found = False
            for request_id in result:
                response = repo_client.get(
                    f"/references/enhancement/batch/request/{request_id}/",
                )
                request = response.json()
                if request["source"].startswith("ImportBatch"):
                    assert request["request_status"] == "completed"
                    import_auto_request_found = True
                if request["source"].startswith("BatchEnhancementRequest"):
                    assert request["request_status"] == "completed"
                    batch_auto_request_found = True

            assert batch_auto_request_found
            assert import_auto_request_found

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
        toys_found = dict.fromkeys(reference_ids, 0)
        for row in result:
            assert str(row.reference_id) in reference_ids
            if row.enhancement_type == "annotation" and row.source == "Toy Robot":
                toys_found[str(row.reference_id)] += 1
        if not all(count == 2 for count in toys_found.values()):
            msg = "Expected toy robot enhancements not found in reference."
            raise AssertionError(msg)

    time.sleep(3)
    es = Elasticsearch(
        os.environ["ES_URL"],
        basic_auth=(os.environ["ES_USER"], os.environ["ES_PASS"]),
        ca_certs=os.environ["ES_CA_PATH"],
    )
    es_index = "destiny-repository-e2e-reference"
    for reference_id in reference_ids:
        response = es.get(index=es_index, id=reference_id)
        toys_found = 0
        for row in response["_source"]["enhancements"]:
            if (
                row["content"]["enhancement_type"] == "annotation"
                and row["source"] == "Toy Robot"
            ):
                toys_found += 1

        if toys_found != 2:
            msg = (
                "Expected toy robot enhancements not found in elasticsearch reference."
            )
            raise AssertionError(msg)

    # Finally, check the import batch's automated enhancements
    es_response = es.search(
        index=es_index,
        query={
            "nested": {
                "path": "identifiers",
                "query": {
                    "bool": {
                        "should": [
                            {
                                "match": {
                                    "identifiers.identifier": "10.1235/sampledoitwoelectricboogaloo"  # noqa: E501
                                }
                            },
                            {"match": {"identifiers.identifier": "W123456790"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            }
        },
    )
    assert es_response["hits"]["total"]["value"] == 2
    for hit in es_response["hits"]["hits"]:
        es_reference = hit["_source"]
        toy_found = False
        for enhancement in es_reference["enhancements"]:
            if (
                enhancement["content"]["enhancement_type"] == "annotation"
                and enhancement["source"] == "Toy Robot"
            ):
                toy_found = True
        if not toy_found:
            msg = (
                "Expected toy robot enhancements not found in elasticsearch reference."
            )
            raise AssertionError(msg)
