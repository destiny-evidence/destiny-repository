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
from uuid import UUID

import destiny_sdk
import httpx


def register_import_record(
    client: httpx.Client, expected_reference_count: int
) -> destiny_sdk.imports.ImportRecordRead:
    """Register a new import record."""
    print("Registering a new import record...")
    response = client.post(
        "/imports/record/",
        json=destiny_sdk.imports.ImportRecordIn(
            processor_name="EPPI Importer GitHub Action",
            processor_version="0.0.1",
            source_name="EPPI",
            expected_reference_count=expected_reference_count,
        ).model_dump(),
    )
    response.raise_for_status()
    import_record = destiny_sdk.imports.ImportRecordRead.model_validate(response.json())
    print(f"Import record {import_record.id} registered.")
    return import_record


def register_import_batch(
    client: httpx.Client, import_record_id: UUID, file_url: str
) -> destiny_sdk.imports.ImportBatchRead:
    """Register an import batch for the given file URL."""
    print(f"Registering import batch for file: {file_url}")
    response = client.post(
        f"/imports/record/{import_record_id}/batch/",
        json=destiny_sdk.imports.ImportBatchIn(
            storage_url=file_url,
            callback_url=None,
        ).model_dump(),
    )
    response.raise_for_status()
    import_batch = destiny_sdk.imports.ImportBatchRead.model_validate(response.json())
    print(f"Import batch {import_batch.id} registered for file {file_url}")
    return import_batch


def finalise_import_record(client: httpx.Client, import_record_id: UUID) -> None:
    """Finalise the import record."""
    print("Finalising import record...")
    response = client.patch(
        f"/imports/record/{import_record_id}/finalise/",
    )
    response.raise_for_status()
    print("Import record finalised.")


def poll_and_summarise(client: httpx.Client, import_batch_id: UUID) -> None:
    """Poll for completion and produce a summary of the import."""
    print(f"Polling import batch {import_batch_id} for completion...")
    for _ in range(5):
        response = client.get(f"/imports/batch/{import_batch_id}/")
        response.raise_for_status()
        import_batch = destiny_sdk.imports.ImportBatchRead.model_validate(
            response.json()
        )
        print(import_batch)
        if import_batch.status == "completed":
            print("Import batch complete.")
            break
        print("Import batch not complete, sleeping for 5 seconds...")
        time.sleep(5)
    else:
        print("Import batch did not complete in time.")

    response = client.get(f"/imports/batch/{import_batch_id}/summary/")
    response.raise_for_status()
    import_batch_summary = destiny_sdk.imports.ImportBatchSummary.model_validate(
        response.json()
    )
    print(f"Import batch {import_batch_id} summary:")
    print(import_batch_summary)


def main() -> None:
    """Post a file to the Destiny API for import."""
    parser = argparse.ArgumentParser(
        description="Posts a single file to the Destiny API for import."
    )
    parser.add_argument("--api-endpoint", required=True, help="Destiny API endpoint")
    parser.add_argument(
        "--access-token", required=True, help="Destiny API access token"
    )
    parser.add_argument("--file-url", required=True, help="URL of the file to import")
    parser.add_argument(
        "--expected-reference-count",
        type=int,
        required=True,
        help="Expected number of references in the import file",
    )
    args = parser.parse_args()

    with httpx.Client(
        base_url=args.api_endpoint,
        headers={"Authorization": f"Bearer {args.access_token}"},
    ) as client:
        import_record = register_import_record(client, args.expected_reference_count)
        import_batch = register_import_batch(client, import_record.id, args.file_url)
        finalise_import_record(client, import_record.id)
        poll_and_summarise(client, import_batch.id)

    print("Import process complete.")


if __name__ == "__main__":
    main()
