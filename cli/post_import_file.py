"""
A utility to post a single file to the Destiny API for import.

Actions:
1. Create an import record
2. Register an import batch for the given file URL
3. Finalise the import record
4. Poll for completion and produce a summary of the import
"""

# ruff: noqa: T201
import sys
import time
from uuid import UUID

import httpx
from destiny_sdk.imports import (
    ImportBatchIn,
    ImportBatchRead,
    ImportBatchStatus,
    ImportRecordIn,
    ImportRecordRead,
)

from cli.client import ApiArgumentParser
from cli.get_import_batch_summary import check_import_batch_status


def register_import_record(  # noqa: PLR0913
    client: httpx.Client,
    expected_reference_count: int,
    processor_name: str,
    processor_version: str,
    source_name: str,
    notes: str | None = None,
) -> ImportRecordRead:
    """Register a new import record."""
    print("Registering a new import record...")
    response = client.post(
        "/imports/records/",
        json=ImportRecordIn(
            processor_name=processor_name,
            processor_version=processor_version,
            source_name=source_name,
            expected_reference_count=expected_reference_count,
            notes=notes,
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
        f"/imports/records/{import_record_id}/batches/",
        json=ImportBatchIn(
            storage_url=file_url,
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
        f"/imports/records/{import_record_id}/finalise/",
    )
    response.raise_for_status()
    print("Import record finalised.")


def poll_and_summarise(
    client: httpx.Client,
    import_record_id: UUID,
    import_batch_id: UUID,
    poll_interval: float = 5,
) -> None:
    """Poll for completion and produce a summary of the import."""
    print(f"Polling import batch {import_batch_id} for completion...")
    for _ in range(10):
        response = client.get(
            f"/imports/records/{import_record_id}/batches/{import_batch_id}/"
        )
        response.raise_for_status()
        import_batch = ImportBatchRead.model_validate(response.json())
        print(import_batch)
        if import_batch.status in ImportBatchStatus.get_terminal_statuses():
            print("Import batch complete.")
            break
        print(f"Import batch not complete, sleeping for {poll_interval} seconds...")
        time.sleep(poll_interval)
    else:
        print("Import batch did not complete in time. Fetching current summary...")

    import_batch_summary = check_import_batch_status(
        client=client,
        import_record_id=import_record_id,
        import_batch_id=import_batch_id,
    )
    print(f"Import batch {import_batch_id} summary:")
    print(import_batch_summary)


def post_import_file(  # noqa: PLR0913
    client: httpx.Client,
    file_url: str,
    expected_reference_count: int,
    processor_name: str,
    processor_version: str,
    source_name: str,
    notes: str | None = None,
    poll_interval: float = 5,
) -> None:
    """Post a file to the Destiny API for import."""
    import_record = register_import_record(
        client,
        expected_reference_count,
        processor_name,
        processor_version,
        source_name,
        notes=notes,
    )
    import_batch = register_import_batch(client, import_record.id, file_url)
    finalise_import_record(client, import_record.id)
    poll_and_summarise(
        client,
        import_record.id,
        import_batch.id,
        poll_interval=poll_interval,
    )

    print("Import process complete.")


def argument_parser() -> ApiArgumentParser:
    """Parse the environment and import file details."""
    parser = ApiArgumentParser(
        description="Posts a single file to the Destiny API for import."
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
    parser.add_argument(
        "--notes",
        default=None,
        help=(
            "Free-text notes stored on the import record "
            "(e.g. reason for importing, known issues)."
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5,
        help="Seconds to wait between import batch status checks (default 5).",
    )
    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with args.client as client:
            post_import_file(
                client=client,
                file_url=args.file_url,
                expected_reference_count=args.expected_reference_count,
                processor_name=args.processor_name,
                processor_version=args.processor_version,
                source_name=args.source_name,
                notes=args.notes,
                poll_interval=args.poll_interval,
            )
    except httpx.HTTPError as exc:
        print(f"Import failed: {exc}")
        sys.exit(1)
