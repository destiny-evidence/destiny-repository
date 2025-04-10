"""End-to-end test for complete import workflow."""
# ruff: noqa: T201 E501

import datetime
import json
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

with Path(os.environ["MINIO_PRESIGNED_URL_FILEPATH"]).open() as f:
    PRESIGNED_URLS: dict[str, str] = json.load(f)

BKT = "e2e/test_complete_batch_import_workflow/"

CALLBACK_URL = os.environ["CALLBACK_URL"]


def test_complete_batch_import_workflow():  # noqa: PLR0915
    """Test the complete batch import workflow."""
    ################################
    # 0. Start the callback server #
    ################################
    callback_app = FastAPI()
    callback_payloads: list[dict] = []

    @callback_app.post("/callback/")
    def callback_endpoint(payload: dict) -> dict:
        """Receive callback payloads."""
        callback_payloads.append(payload)
        return {"status": "received"}

    def run_callback_server() -> None:
        """Run the FastAPI server."""
        print("Starting callback server...")
        uvicorn.run(callback_app, host="0.0.0.0", port=8001)  # noqa: S104

    server_thread = threading.Thread(target=run_callback_server, daemon=True)
    server_thread.start()

    with httpx.Client(base_url=os.environ["REPO_URL"]) as client:
        #############################
        # 1. Register import record #
        #############################
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

        ##########################################
        # 2. Enqueue import batch for each file  #
        ##########################################
        # 2.a: A detailed import file with valid records
        url = PRESIGNED_URLS[f"{BKT}1_completely_valid_file.jsonl"]
        # 2.a.1: Missing import record id
        response = client.post(
            "/imports/record/batch/",
            json={
                "storage_url": url,
            },
        )
        assert response.status_code == 405
        # 2.a.2 Invalid enum
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "collision_strategy": "https://www.reddit.com/r/ProgrammerHumor/comments/cgf0b8/git_merge/",
            },
        )
        assert response.status_code == 422
        # 2.a.3: Wrong import record
        response = client.post(
            f"/imports/record/{(u:=uuid.uuid4())}/batch/",
            json={
                "storage_url": url,
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == f"Import record with id {u} not found."
        # 2.a.4: Correct batch creation
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_a = response.json()
        assert import_batch_a["id"] is not None
        assert import_batch_a["storage_url"] == url
        assert import_batch_a["import_record_id"] == import_record["id"]
        assert import_batch_a["collision_strategy"] == "fail"
        assert import_batch_a["callback_url"] == f"{CALLBACK_URL}/callback/"
        # 2.a.5: Duplicate URL
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        # TODO(Adam): add application logic to make this return 409  # noqa: TD003
        assert response.status_code == 500

        time.sleep(1)

        # 2.b: An import file with invalid records
        url = PRESIGNED_URLS[f"{BKT}2_file_with_some_failures.jsonl"]
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_b = response.json()
        assert import_batch_b["id"] is not None
        assert import_batch_b["import_record_id"] == import_record["id"]

        # 2.c: Duplicate entries for each in 2.a
        url = PRESIGNED_URLS[f"{BKT}3_file_with_duplicates.jsonl"]
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "collision_strategy": "fail",
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_c = response.json()
        assert import_batch_c["id"] is not None
        assert import_batch_c["import_record_id"] == import_record["id"]
        assert import_batch_c["collision_strategy"] == "fail"
        assert import_batch_c["callback_url"] == f"{CALLBACK_URL}/callback/"
        assert import_batch_c["storage_url"] == url

        # 2.d: Subset of duplicates, overwriting
        url = PRESIGNED_URLS[f"{BKT}4_file_with_duplicates_to_overwrite.jsonl"]
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "collision_strategy": "overwrite",
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_d = response.json()
        assert import_batch_d["id"] is not None
        assert import_batch_d["import_record_id"] == import_record["id"]
        assert import_batch_d["collision_strategy"] == "overwrite"
        assert import_batch_d["callback_url"] == f"{CALLBACK_URL}/callback/"
        assert import_batch_d["storage_url"] == url

        # 2.e: Subset of duplicates, defensive merge
        url = PRESIGNED_URLS[f"{BKT}5_file_with_duplicates_to_left_merge.jsonl"]
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "collision_strategy": "merge_defensive",
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_e = response.json()
        assert import_batch_e["id"] is not None
        assert import_batch_e["import_record_id"] == import_record["id"]
        assert import_batch_e["collision_strategy"] == "merge_defensive"
        assert import_batch_e["callback_url"] == f"{CALLBACK_URL}/callback/"
        assert import_batch_e["storage_url"] == url

        # 2.f: Subset of duplicates, aggressive merge
        url = PRESIGNED_URLS[f"{BKT}6_file_with_duplicates_to_right_merge.jsonl"]
        response = client.post(
            f"/imports/record/{import_record['id']}/batch/",
            json={
                "storage_url": url,
                "collision_strategy": "merge_aggressive",
                "callback_url": f"{CALLBACK_URL}/callback/",
            },
        )
        assert response.status_code == 202
        import_batch_f = response.json()
        assert import_batch_f["id"] is not None
        assert import_batch_f["import_record_id"] == import_record["id"]
        assert import_batch_f["collision_strategy"] == "merge_aggressive"
        assert import_batch_f["callback_url"] == f"{CALLBACK_URL}/callback/"
        assert import_batch_f["storage_url"] == url

    # wait a sensible amount of time for batches to complete
    # not required until distributed tasks are implemented
    # time.sleep(20) # noqa: ERA001

    ##########################
    # 3. Callback validation #
    ##########################
    # 2.a callback verification
    assert callback_payloads[0]["import_batch_id"] == import_batch_a["id"]
    assert callback_payloads[0]["import_batch_status"] == "completed"
    assert sum(callback_payloads[0]["results"].values()) == 6
    assert callback_payloads[0]["results"]["completed"] == 6
    assert not callback_payloads[0]["failure_details"]
    # 2.b callback verification
    assert callback_payloads[1]["import_batch_id"] == import_batch_b["id"]
    assert callback_payloads[1]["import_batch_status"] == "completed"
    assert sum(callback_payloads[1]["results"].values()) == 9
    assert callback_payloads[1]["results"]["failed"] == 5
    assert callback_payloads[1]["results"]["partially_failed"] == 3
    assert callback_payloads[1]["results"]["completed"] == 1
    assert len(callback_payloads[1]["failure_details"]) == 8
    assert "Entry 2:" in callback_payloads[1]["failure_details"][0]
    assert "identifiers\n  Field required" in callback_payloads[1]["failure_details"][0]
    assert (
        "identifiers\n  List should have at least 1 item"
        in callback_payloads[1]["failure_details"][1]
    )
    assert (
        "identifiers\n  Input should be a valid list"
        in callback_payloads[1]["failure_details"][2]
    )
    assert (
        "All identifiers failed to parse." in callback_payloads[1]["failure_details"][3]
    )
    assert (
        "Enhancement 1:\n    Invalid enhancement. Check the format and content of the enhancement."
        in callback_payloads[1]["failure_details"][4]
    )
    assert (
        "All identifiers failed to parse." in callback_payloads[1]["failure_details"][5]
    )
    assert (
        "Identifier 1:\n    Invalid identifier."
        in callback_payloads[1]["failure_details"][5]
    )
    assert (
        "Identifier 2:\n    Invalid identifier."
        in callback_payloads[1]["failure_details"][5]
    )
    assert (
        "Entry 8:\n\nEnhancement 2:\n    Invalid enhancement. Check the format and content of the enhancement."
        in callback_payloads[1]["failure_details"][6]
    )
    assert (
        "Enhancement 1:\n    Invalid enhancement. Check the format and content of the enhancement."
        in callback_payloads[1]["failure_details"][7]
    )
    # 2.c callback verification
    assert callback_payloads[2]["import_batch_id"] == import_batch_c["id"]
    assert callback_payloads[2]["import_batch_status"] == "completed"
    assert sum(callback_payloads[2]["results"].values()) == 7
    assert callback_payloads[2]["results"]["failed"] == 7
    for i, failure in enumerate(callback_payloads[2]["failure_details"][:6]):
        assert f"Entry {i + 1}:" in failure
        assert "Identifier(s) are already mapped on an existing reference" in failure
    assert (
        callback_payloads[2]["failure_details"][6]
        == "Entry 7:\n\nIncoming reference collides with more than one existing reference."
    )
    # 2.d callback verification
    assert callback_payloads[3]["import_batch_id"] == import_batch_d["id"]
    assert callback_payloads[3]["import_batch_status"] == "completed"
    assert sum(callback_payloads[3]["results"].values()) == 3
    assert callback_payloads[3]["results"]["failed"] == 1
    assert callback_payloads[3]["results"]["completed"] == 2
    assert len(callback_payloads[3]["failure_details"]) == 1
    assert (
        callback_payloads[3]["failure_details"][0]
        == "Entry 3:\n\nIncoming reference collides with more than one existing reference."
    )
    # 2.e callback verification
    assert callback_payloads[4]["import_batch_id"] == import_batch_e["id"]
    assert callback_payloads[4]["import_batch_status"] == "completed"
    assert sum(callback_payloads[4]["results"].values()) == 2
    assert callback_payloads[4]["results"]["completed"] == 2
    assert not callback_payloads[4]["failure_details"]
    # 2.f callback verification
    assert callback_payloads[5]["import_batch_id"] == import_batch_f["id"]
    assert callback_payloads[5]["import_batch_status"] == "completed"
    assert sum(callback_payloads[5]["results"].values()) == 2
    assert callback_payloads[5]["results"]["completed"] == 2
    assert not callback_payloads[5]["failure_details"]

    ################################
    # 4. Database state validation #
    ################################
