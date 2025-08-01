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
import sys
import time
from uuid import UUID

import httpx
from destiny_sdk.imports import (
    CollisionStrategy,
    ImportBatchIn,
    ImportBatchRead,
    ImportBatchSummary,
    ImportRecordIn,
    ImportRecordRead,
)


def register_import_record(
    client: httpx.Client,
    expected_reference_count: int,
    processor_name: str,
    processor_version: str,
    source_name: str,
) -> ImportRecordRead:
    """Register a new import record."""
    print("Registering a new import record...")
    response = client.post(
        "/imports/record/",
        json=ImportRecordIn(
            processor_name=processor_name,
            processor_version=processor_version,
            source_name=source_name,
            expected_reference_count=expected_reference_count,
        ).model_dump(mode="json"),
    )
    response.raise_for_status()
    import_record = ImportRecordRead.model_validate(response.json())
    print(f"Import record {import_record.id} registered.")
    return import_record


def register_import_batch(
    client: httpx.Client, import_record_id: UUID, file_url: str
) -> ImportBatchRead:
    """Register an import batch for the given file URL."""
    print(f"Registering import batch for file: {file_url}")
    response = client.post(
        f"/imports/record/{import_record_id}/batch/",
        json=ImportBatchIn(
            collision_strategy=CollisionStrategy.MERGE_DEFENSIVE,
            storage_url=file_url,
            callback_url=None,
        ).model_dump(mode="json"),
    )
    response.raise_for_status()
    import_batch = ImportBatchRead.model_validate(response.json())
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
        import_batch = ImportBatchRead.model_validate(response.json())
        print(import_batch)
        if import_batch.status == "completed":
            print("Import batch complete.")
            break
        print("Import batch not complete, sleeping for 5 seconds...")
        time.sleep(5)
    else:
        print("Import batch did not complete in time.")
        sys.exit(1)

    response = client.get(f"/imports/batch/{import_batch_id}/summary/")
    response.raise_for_status()
    import_batch_summary = ImportBatchSummary.model_validate(response.json())
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
    parser.add_argument(
        "--processor-name",
        required=True,
        help="Name of the processor (e.g., workflow or script)",
    )
    parser.add_argument(
        "--processor-version",
        required=True,
        help="Version of the processor (e.g., workflow or script version)",
    )
    parser.add_argument(
        "--source-name",
        required=True,
        help="Source name for the import (e.g., EPPI)",
    )
    args = parser.parse_args()

    with httpx.Client(
        base_url=args.api_endpoint,
        headers={"Authorization": f"Bearer {args.access_token}"},
    ) as client:
        import_record = register_import_record(
            client,
            args.expected_reference_count,
            args.processor_name,
            args.processor_version,
            args.source_name,
        )
        import_batch = register_import_batch(client, import_record.id, args.file_url)
        finalise_import_record(client, import_record.id)
        poll_and_summarise(client, import_batch.id)

    print("Import process complete.")


if __name__ == "__main__":
    main()
