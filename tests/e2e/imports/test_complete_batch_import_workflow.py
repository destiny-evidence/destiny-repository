"""
End-to-end test for complete import workflow.

Consider reducing number of assertions, particularly string-sensitive, once
unit and integration test coverage is sound.

N.B. does NOT use the SDK in order to test serverside validation.
"""
# ruff: noqa: T201 E501 ERA001

import datetime
import json
import os
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine, text

with Path(os.environ["MINIO_PRESIGNED_URL_FILEPATH"]).open() as f:
    PRESIGNED_URLS: dict[str, str] = json.load(f)

BKT = "e2e/test_complete_batch_import_workflow/"

CALLBACK_URL = os.environ["CALLBACK_URL"]

callback_payload: dict = {}

db_url = os.environ["DB_URL"]
engine = create_engine(db_url)


def test_complete_batch_import_workflow():  # noqa: PLR0915
    """Test the complete batch import workflow."""
    #############################
    # Start the callback server #
    #############################
    callback_app = FastAPI()

    @callback_app.post("/callback/")
    def callback_endpoint(payload: dict) -> dict:
        """Receive callback payloads."""
        callback_payload.clear()
        callback_payload.update(payload)
        return {"status": "received"}

    # Helper to wait for a callback and then clear it
    def wait_for_callback(timeout: int = 10) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            if callback_payload:
                cp = callback_payload.copy()
                callback_payload.clear()
                return cp
            time.sleep(0.1)
        msg = "Callback not received in time"
        raise TimeoutError(msg)

    def run_callback_server() -> None:
        """Run the FastAPI server."""
        print("Starting callback server...")
        uvicorn.run(callback_app, host="0.0.0.0", port=8001)  # noqa: S104

    server_thread = threading.Thread(target=run_callback_server, daemon=True)
    server_thread.start()

    def get_reference_details() -> list[dict]:
        """Get reference details from the database."""
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                SELECT *
                FROM reference r
                LEFT JOIN enhancement e ON r.id = e.reference_id
                JOIN external_identifier i ON r.id = i.reference_id;
                """)
            )
            references: dict[uuid.UUID, dict[str, list[dict]]] = defaultdict(
                lambda: {"enhancements": [], "identifiers": []}
            )
            for row in result:
                references[row.reference_id]["enhancements"].append(
                    {
                        "enhancement_type": row.enhancement_type,
                        "enhancement_content": json.loads(row.content)
                        if row.content
                        else None,
                        "source": row.source,
                    }
                )
                references[row.reference_id]["identifiers"].append(
                    {
                        "identifier_type": row.identifier_type,
                        "identifier": row.identifier,
                        "other_identifier_name": row.other_identifier_name,
                    }
                )
            return [
                {
                    "reference_id": ref_id,
                    "enhancements": details["enhancements"],
                    "identifiers": details["identifiers"],
                }
                for ref_id, details in sorted(references.items())
            ]

    with httpx.Client(base_url=os.environ["REPO_URL"]) as client:
        ##########################
        # Register import record #
        ##########################
        # 1.a: Missing source name
        response = client.post(
            "/imports/record/",
            json={
                "processor_name": "test_processor",
                "processor_version": "0.0.1",
            },
        )
        assert response.status_code == 422
        # 1.b: Wrong data type on reference count
        response = client.post(
            "/imports/record/",
            json={
                "processor_name": "test_processor",
                "processor_version": "0.0.1",
                "expected_reference_count": "over nine thousand",
                "source_name": "test_source",
            },
        )
        assert response.status_code == 422
        # 1.c: Correct record (with minimal fields)
        response = client.post(
            "/imports/record/",
            json={
                "processor_name": "test_processor",
                "processor_version": "0.0.1",
                "source_name": "test_source",
                "expected_reference_count": -1,
            },
        )
        assert response.status_code == 201
        import_record = response.json()
        assert import_record["id"] is not None
        assert import_record["status"] == "created"
        assert import_record["processor_name"] == "test_processor"
        assert import_record["processor_version"] == "0.0.1"
        assert import_record["source_name"] == "test_source"
        assert import_record["expected_reference_count"] == -1
        assert datetime.datetime.strptime(
            import_record["searched_at"], "%Y-%m-%dT%H:%M:%S.%f%z"
        ) > datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(minutes=1)

        #######################################
        # Enqueue import batch for each file  #
        #######################################
        # Define helper to factorise batch submission
        def submit_happy_batch(
            import_record_id: str, url: str, **kwargs: object
        ) -> dict:
            response = client.post(
                f"/imports/record/{import_record_id}/batch/",
                json={"storage_url": url, **kwargs},
            )
            assert (
                response.status_code == 202
            ), f"Expected 202, got {response.status_code}"
            return response.json()

        # 2: A detailed import file with valid records
        url = PRESIGNED_URLS[f"{BKT}1_completely_valid_file.jsonl"]
        # 2.a: Missing import record id
        response = client.post(
            "/imports/record/batch/",
            json={
                "storage_url": url,
            },
        )
        assert response.status_code == 405
        # 2.b: Invalid enum
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "collision_strategy": "https://www.reddit.com/r/ProgrammerHumor/comments/cgf0b8/git_merge/",
            },
        )
        assert response.status_code == 422
        # 2.c: Wrong import record
        response = client.post(
            f"/imports/record/{(u:=uuid.uuid4())}/batch/",
            json={
                "storage_url": url,
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == f"Unable to find ImportRecord with pk {u}"
        # 2.d: Correct batch creation
        import_batch_a = submit_happy_batch(
            import_record["id"],
            url,
            callback_url=f"{CALLBACK_URL}/callback/",
        )

        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_a["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 6
        assert cp["results"]["completed"] == 6
        assert not cp["failure_details"]

        # Check an import
        rd = get_reference_details()
        assert len(rd) == 6

        response = client.get(
            "/references/",
            params={
                "identifier_type": "doi",
                "identifier": "10.1234/sampledoi",
            },
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 2
        assert len(reference["identifiers"]) == 2

        # 2.e: Duplicate URL
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code in (409, 500)

        # 3: An import file with invalid records
        url = PRESIGNED_URLS[f"{BKT}2_file_with_some_failures.jsonl"]
        import_batch_b = submit_happy_batch(
            import_record["id"],
            url,
            callback_url=f"{CALLBACK_URL}/callback/",
        )
        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_b["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 9
        assert cp["results"]["failed"] == 5
        assert cp["results"]["partially_failed"] == 3
        assert cp["results"]["completed"] == 1
        assert len(cp["failure_details"]) == 8
        assert "Entry 2:" in cp["failure_details"][0]
        assert "identifiers\n  Field required" in cp["failure_details"][0]
        assert (
            "identifiers\n  List should have at least 1 item"
            in cp["failure_details"][1]
        )
        assert "identifiers\n  Input should be a valid list" in cp["failure_details"][2]
        assert "All identifiers failed to parse." in cp["failure_details"][3]
        assert (
            "Enhancement 1:\n    Invalid enhancement. Check the format and content of the enhancement."
            in cp["failure_details"][4]
        )
        assert "All identifiers failed to parse." in cp["failure_details"][5]
        assert "Identifier 1:\n    Invalid identifier." in cp["failure_details"][5]
        assert "Identifier 2:\n    Invalid identifier." in cp["failure_details"][5]
        assert (
            "Entry 8:\n\nEnhancement 2:\n    Invalid enhancement. Check the format and content of the enhancement."
            in cp["failure_details"][6]
        )
        assert (
            "Enhancement 1:\n    Invalid enhancement. Check the format and content of the enhancement."
            in cp["failure_details"][7]
        )

        rd = get_reference_details()
        assert len(rd) == 10

        # Check the import of a partial failure
        response = client.get(
            "/references/",
            params={"identifier_type": "open_alex", "identifier": "W123456793"},
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 0
        assert len(reference["identifiers"]) == 1

        # 4: Duplicate entries for each in 2
        url = PRESIGNED_URLS[f"{BKT}3_file_with_duplicates.jsonl"]
        import_batch_c = submit_happy_batch(
            import_record["id"],
            url,
            collision_strategy="fail",
            callback_url=f"{CALLBACK_URL}/callback/",
        )
        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_c["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 7
        assert cp["results"]["failed"] == 7
        for i, failure in enumerate(cp["failure_details"][:6]):
            assert f"Entry {i + 1}:" in failure
            assert (
                "Identifier(s) are already mapped on an existing reference" in failure
            )
        assert (
            cp["failure_details"][6]
            == "Entry 7:\n\nIncoming reference collides with more than one existing reference."
        )

        rd = get_reference_details()
        assert len(rd) == 10

        # 5: Subset of duplicates, overwriting
        url = PRESIGNED_URLS[f"{BKT}4_file_with_duplicates_to_overwrite.jsonl"]
        import_batch_d = submit_happy_batch(
            import_record["id"],
            url,
            collision_strategy="overwrite",
            callback_url=f"{CALLBACK_URL}/callback/",
        )
        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_d["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 3
        assert cp["results"]["failed"] == 1
        assert cp["results"]["completed"] == 2
        assert len(cp["failure_details"]) == 1
        assert (
            cp["failure_details"][0]
            == "Entry 3:\n\nIncoming reference collides with more than one existing reference."
        )

        rd = get_reference_details()
        assert len(rd) == 10

        # Same reference as in part 2
        # Check that the number of enhancements has reduced, and that the number of identifiers has increased
        response = client.get(
            "/references/",
            params={
                "identifier_type": "doi",
                "identifier": "10.1234/sampledoi",
            },
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 1
        assert len(reference["identifiers"]) == 3

        # 6: Subset of duplicates, defensive merge
        url = PRESIGNED_URLS[f"{BKT}5_file_with_duplicates_to_left_merge.jsonl"]
        import_batch_e = submit_happy_batch(
            import_record["id"],
            url,
            collision_strategy="merge_defensive",
            callback_url=f"{CALLBACK_URL}/callback/",
        )
        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_e["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 2
        assert cp["results"]["completed"] == 2
        assert not cp["failure_details"]

        # Check that the enhancement did not update (since defensive)
        response = client.get(
            "/references/",
            params={
                "identifier_type": "other",
                "identifier": "1234567891011",
                "other_identifier_name": "ISBN",
            },
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 3
        assert len(reference["identifiers"]) == 2
        for enhancement in reference["enhancements"]:
            if enhancement["content"]["enhancement_type"] == "bibliographic":
                assert enhancement["content"]["cited_by_count"] == 5
        # Check that the next reference did add a new enhancement
        response = client.get(
            "/references/",
            params={
                "identifier_type": "pm_id",
                "identifier": "55555",
            },
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 3
        assert len(reference["identifiers"]) == 2

        # 7: Subset of duplicates, aggressive merge
        url = PRESIGNED_URLS[f"{BKT}6_file_with_duplicates_to_right_merge.jsonl"]
        import_batch_f = submit_happy_batch(
            import_record["id"],
            url,
            collision_strategy="merge_aggressive",
            callback_url=f"{CALLBACK_URL}/callback/",
        )
        cp = wait_for_callback()
        assert cp["import_batch_id"] == import_batch_f["id"]
        assert cp["import_batch_status"] == "completed"
        assert sum(cp["results"].values()) == 2
        assert cp["results"]["completed"] == 2
        assert not cp["failure_details"]

        # Check that the existing enhancement & identifier updated, and new identifier added
        response = client.get(
            "/references/",
            params={
                "identifier_type": "open_alex",
                "identifier": "W123456791",
            },
        )
        assert response.status_code == 200
        reference = response.json()
        assert len(reference["enhancements"]) == 1
        assert len(reference["identifiers"]) == 3
        for identifier in reference["identifiers"]:
            if identifier["identifier_type"] == "doi":
                assert (
                    identifier["identifier"] == "10.1235/sampledoitwoelectricboogaloo"
                )
        for enhancement in reference["enhancements"]:
            if enhancement["content"]["enhancement_type"] == "bibliographic":
                assert (
                    enhancement["content"]["authorship"][0]["display_name"] == "Wynstan"
                )

        # 8: Mark import record as completed
        response = client.patch(
            f"/imports/record/{import_record['id']}/finalise/",
        )
        assert response.status_code == 204
        response = client.get(
            f"/imports/record/{import_record['id']}/",
        )
        assert response.status_code == 200
        import_record = response.json()
        assert import_record["status"] == "completed"
