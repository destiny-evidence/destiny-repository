# ruff: noqa: T201
"""
Posts a single file to the Destiny API for import.

Actions:
1. Create an import record
2. Register an import batch for the given file URL
3. Finalise the import record
4. Poll for completion and produce a summary of the import
"""

import argparse
import time

import destiny_sdk
import httpx

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Posts a single file to the Destiny API for import."
    )
    parser.add_argument("--api-endpoint", required=True, help="Destiny API endpoint")
    parser.add_argument(
        "--access-token", required=True, help="Destiny API access token"
    )
    parser.add_argument("--file-url", required=True, help="URL of the file to import")
    args = parser.parse_args()

    API_HOST = args.api_endpoint

    with httpx.Client(
        base_url=API_HOST,
        headers={"Authorization": f"Bearer {args.access_token}"},
    ) as client:
        # 1: Register a new import
        response = client.post(
            "/imports/record/",
            json=destiny_sdk.imports.ImportRecordIn(
                processor_name="EPPI Importer GitHub Action",
                processor_version="0.0.1",
                source_name="EPPI",
                # This is a placeholder, as we don't know the exact count
                expected_reference_count=1,
            ),
        )
        response.raise_for_status()
        import_record = destiny_sdk.imports.ImportRecordRead.model_validate(
            response.json()
        )

        # 2: Register an import batch for the file
        import_batch_ids = []
        print("Registering import batch for file:", args.file_url)
        response = client.post(
            f"/imports/record/{import_record.id}/batch/",
            json=destiny_sdk.imports.ImportBatchIn(
                storage_url=args.file_url,
                callback_url=None,
            ),
        )
        response.raise_for_status()
        import_batch = destiny_sdk.imports.ImportBatchRead.model_validate(
            response.json()
        )
        print(f"Import batch {import_batch.id} registered for file {args.file_url}")

        import_batch_ids.append(import_batch.id)

        # 3: Finalise the import record
        print("Finalising import record")
        response = client.patch(
            f"/imports/record/{import_record.id}/finalise/",
        )
        response.raise_for_status()

        # 4: Produce a summary of the import
        for import_batch_id in import_batch_ids:
            # Poll to check if complete
            print(f"Polling import batch {import_batch_id} for completion")
            i = 0
            while i < 5:  # noqa: PLR2004
                response = client.get(
                    f"/imports/batch/{import_batch_id}/",
                )
                response.raise_for_status()
                import_batch = destiny_sdk.imports.ImportBatchRead.model_validate(
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
