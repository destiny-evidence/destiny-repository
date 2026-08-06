"""
A utility to copy references from one environment into another.

Actions:
1. Export the references from the source, in chunks
2. Register each export file as a batch of one import record in the destination
3. Finalise the record and summarise each batch

Export files are passed on by URL, never rewritten.

*NOTE* This is lossy:
- ``derived_from``, ``robot_version``, all ``id``s and all timestamps are dropped
- duplicate clusters collapse into one reference holding the union of their content
- the destination re-runs deduplication over its own corpus

*BONUS*: It's totally valid to have a local `dest` if you want some remote references!
"""

# ruff: noqa: T201
import sys
import time
from typing import TYPE_CHECKING

import httpx
from destiny_sdk.references import ExportStatus, ReferenceExportRead

from app.core.config import Environment
from app.utils.lists import list_chunker
from cli.client import ApiArgumentParser, get_client
from cli.post_import_file import (
    finalise_import_record,
    poll_and_summarise,
    register_import_batch,
    register_import_record,
)

if TYPE_CHECKING:
    from uuid import UUID

_DEFAULT_EXPORT_CHUNK_SIZE = 10_000


def request_export(
    client: httpx.Client,
    reference_ids: list[str],
    poll_interval: float,
    max_polls: int,
) -> ReferenceExportRead:
    """Queue an export of the given references and poll it to completion."""
    response = client.post("/references/exports/", json=reference_ids)
    response.raise_for_status()
    export = ReferenceExportRead.model_validate(response.json())
    print(f"Export {export.id} queued for {len(reference_ids)} references.")

    for _ in range(max_polls):
        if export.status in (ExportStatus.COMPLETED, ExportStatus.FAILED):
            break
        time.sleep(poll_interval)
        response = client.get(f"/references/exports/{export.id}/")
        response.raise_for_status()
        export = ReferenceExportRead.model_validate(response.json())
        print(f"Export {export.id} status: {export.status}")
    else:
        msg = f"Export {export.id} did not complete after {max_polls} polls."
        raise TimeoutError(msg)

    if export.status is ExportStatus.FAILED or not export.result_url:
        msg = f"Export {export.id} failed: {export.error}"
        raise RuntimeError(msg)

    print(f"Export {export.id} complete: {export.n_references} references.")
    return export


def migrate_references(  # noqa: PLR0913
    source_client: httpx.Client,
    dest_client: httpx.Client,
    source_env: Environment,
    reference_ids: list[str],
    notes: str,
    export_chunk_size: int = _DEFAULT_EXPORT_CHUNK_SIZE,
    poll_interval: float = 5,
    max_polls: int = 60,
    *,
    dry_run: bool = False,
) -> None:
    """Copy the given references from the source environment to the destination."""
    reference_ids = list(dict.fromkeys(reference_ids))
    chunks = list(list_chunker(reference_ids, export_chunk_size))

    if dry_run:
        print(
            f"DRY-RUN: would export {len(reference_ids)} references from the source "
            f"in {len(chunks)} chunk(s) and import them as {len(chunks)} batch(es)."
        )
        return

    import_record = register_import_record(
        dest_client,
        expected_reference_count=len(reference_ids),
        processor_name="cli.migrate_references",
        processor_version="1.0.0",
        source_name=f"destiny-repository-{source_env.value}",
        notes=notes,
    )

    # A chunk at a time: the signed URLs in each export are short lived, so hand
    # them over as they complete rather than banking them all up front.
    batch_ids: list[UUID] = []
    for i, chunk in enumerate(chunks, start=1):
        print(f"\nChunk {i}/{len(chunks)} ({len(chunk)} references):")
        export = request_export(source_client, chunk, poll_interval, max_polls)
        batch = register_import_batch(
            dest_client, import_record.id, str(export.result_url)
        )
        batch_ids.append(batch.id)

    finalise_import_record(dest_client, import_record.id)

    for batch_id in batch_ids:
        poll_and_summarise(
            dest_client,
            import_record.id,
            batch_id,
            poll_interval=poll_interval,
        )

    print(f"\nMigration complete under import record {import_record.id}.")


def argument_parser() -> ApiArgumentParser:
    """Parse the source and destination environments and the id file."""
    parser = ApiArgumentParser(
        description=(
            "Copies references from --env into --dest-env, which may not be "
            "production."
        )
    )

    parser.add_argument(
        "--reference-id-file",
        required=True,
        help="Path to a file of newline-delimited reference ids in the source.",
    )
    parser.add_argument(
        "--dest-env",
        type=Environment,
        choices=[env for env in Environment if env is not Environment.PRODUCTION],
        required=True,
        help="Environment to migrate into. Cannot be production.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Notes for the destination import record. Defaults to a summary.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5,
        help="Seconds to wait between status checks (default 5).",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=60,
        help="Status checks to make per export before giving up (default 60).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would move, without moving it.",
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with open(args.reference_id_file) as ref_id_file:  # noqa: PTH123
            reference_ids = [
                line.strip() for line in ref_id_file.read().splitlines() if line.strip()
            ]
        if not reference_ids:
            msg = f"No reference ids found in {args.reference_id_file}."
            raise ValueError(msg)  # noqa: TRY301

        print(
            f"Migrating {len(reference_ids)} references "
            f"{args.env.value} -> {args.dest_env.value}."
        )

        with (
            args.client as source_client,
            get_client(args.dest_env) as dest_client,
        ):
            migrate_references(
                source_client=source_client,
                dest_client=dest_client,
                source_env=args.env,
                reference_ids=reference_ids,
                notes=args.notes
                or f"Migrated from {args.env.value} via cli.migrate_references.",
                poll_interval=args.poll_interval,
                max_polls=args.max_polls,
                dry_run=args.dry_run,
            )

    except (httpx.HTTPError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Migration failed: {exc}")
        sys.exit(1)
