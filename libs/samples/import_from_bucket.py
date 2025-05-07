# ruff: noqa: T201
"""
Import the entire contents of a bucket into the repository.

Actions:
1. Create an import record
2. Register an import batch for each file in the bucket
3. Finalise the import record
4. Produce a summary of the import

Not implemented:
- Receiving callbacks
- Marshalling objects using SDK

Note:
- The file format is well-formed per the documentation
- This sample purely imports - you can also update using existing identifiers and a
  different collision strategy

Example command to run (NB most are relevant to the blob storage, not the API):
ACCOUNT_NAME=destinyrepositorystag \
ACCOUNT_KEY=<redacted> \
CONTAINER_NAME=tmp-sample-batch-import \
ACCESS_TOKEN=<redacted> \
python import_from_bucket.py

"""

import datetime
import os
import time

import destiny_sdk
import httpx
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

if __name__ == "__main__":
    ACCOUNT_NAME = os.environ["ACCOUNT_NAME"]
    ACCOUNT_KEY = os.environ["ACCOUNT_KEY"]
    CONTAINER_NAME = os.environ["CONTAINER_NAME"]
    API_HOST = os.getenv("API_HOST", "http://127.0.0.1:8000")

    with httpx.Client(
        base_url=API_HOST,
        headers={"Authorization": f"Bearer {os.environ['ACCESS_TOKEN']}"},
    ) as client:
        # 1: Register a new import
        response = client.post(
            "/imports/record/",
            json=destiny_sdk.imports.ImportRecordIn(
                processor_name="Sample bulk importer",
                processor_version="0.0.1",
                source_name="OpenAlex",
                expected_reference_count=6,
            ),
        )
        response.raise_for_status()
        import_record = destiny_sdk.imports.ImportRecord.model_validate(response.json())

        # 2: For each file in the bucket, register an import batch
        blob_service_client = BlobServiceClient(
            account_url=f"https://{ACCOUNT_NAME}.blob.core.windows.net",
            credential=ACCOUNT_KEY,
        )

        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs()

        import_batch_ids = []
        for blob in blobs:
            print("Generating SAS token for blob:", blob.name)
            sas_token = generate_blob_sas(
                account_name=ACCOUNT_NAME,
                container_name=CONTAINER_NAME,
                blob_name=blob.name,
                account_key=ACCOUNT_KEY,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            )

            sas_url = f"https://{ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{blob.name}?{sas_token}"

            print("Registering import batch for blob:", blob.name)
            response = client.post(
                f"/imports/record/{import_record.id}/batch/",
                json=destiny_sdk.imports.ImportBatchIn(
                    storage_url=sas_url,
                    callback_url=None,
                ),
            )
            response.raise_for_status()
            import_batch = destiny_sdk.imports.ImportBatch.model_validate(
                response.json()
            )
            print(f"Import batch {import_batch.id} registered for blob {blob.name}")

            import_batch_ids.append(import_batch.id)

        # 3: Finalise the import record
        print("Finalising import record")
        response = client.patch(
            f"/imports/record/{import_record.id}/finalise/",
        )
        response.raise_for_status()

        # 4: Produce a summary of the import (since we aren't receiving a callback here)
        for import_batch_id in import_batch_ids:
            # Poll to check if complete
            print(f"Polling import batch {import_batch_id} for completion")
            i = 0
            while i < 5:  # noqa: PLR2004
                response = client.get(
                    f"/imports/batch/{import_batch_id}/",
                )
                response.raise_for_status()
                import_batch = destiny_sdk.imports.ImportBatch.model_validate(
                    response.json()
                )
                print(import_batch)
                if import_batch.status == "completed":
                    break
                i += 1
                print("Import batch not complete, sleeping for 5 seconds")
                time.sleep(5)

            response = client.get(
                f"/imports/batch/{import_batch_id}/summary/",
            )
            response.raise_for_status()
            import_batch_summary = (
                destiny_sdk.imports.ImportBatchSummary.model_validate(response.json())
            )
            print(f"Import batch {import_batch_id} summary:")
            print(import_batch_summary)

    print("Import process complete")
