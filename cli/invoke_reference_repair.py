"""A utility to invoke subset repair on a file of reference_ids."""

# ruff: noqa: T201
from pathlib import Path

import httpx
from fastapi import status

from app.utils.lists import list_chunker
from cli.client import ApiArgumentParser

_REPAIR_PATH = "/system/indices/reference/repair/"


def invoke_reference_repair(
    client: httpx.Client,
    reference_ids: list[str],
    batch_size: int = 1000,
    start_batch: int = 1,
    *,
    dry_run: bool = False,
) -> int:
    """Invoke subset repair on a list of reference ids in batches."""
    batches = list(list_chunker(reference_ids, batch_size))

    if dry_run:
        print(f"DRY-RUN: would POST {len(batches)} batches to {_REPAIR_PATH}")
        for i, batch in enumerate(batches, start=1):
            if i < start_batch:
                continue
            print(
                f"  Batch {i}/{len(batches)}: {len(batch)} ids "
                f"(first: {batch[0]}, last: {batch[-1]})"
            )
        return len(reference_ids)

    for i, batch in enumerate(batches, start=1):
        if i < start_batch:
            continue
        print(
            f"POST batch {i}/{len(batches)} ({len(batch)} ids)...",
            end=" ",
            flush=True,
        )
        response = client.post(
            _REPAIR_PATH,
            json={"document_ids": batch},
            timeout=60,
        )
        print(f"{response.status_code}")
        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            msg = response.json().get("detail", response.text)
            raise httpx.HTTPError(msg)

    return len(reference_ids)


def argument_parser() -> ApiArgumentParser:
    """Parse the environment, ID file path, and batching options."""
    parser = ApiArgumentParser()

    parser.add_argument(
        "--reference-id-file",
        type=str,
        required=True,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="IDs per request (default 1000, matches server max).",
    )

    parser.add_argument(
        "--start-batch",
        type=int,
        default=1,
        help="1-indexed batch to resume from after a partial failure.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be POSTed without sending requests.",
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with Path.open(args.reference_id_file) as ref_id_file:
            reference_ids = ref_id_file.read().splitlines()

        with args.client as client:
            invoke_reference_repair(
                client=client,
                reference_ids=reference_ids,
                batch_size=args.batch_size,
                start_batch=args.start_batch,
                dry_run=args.dry_run,
            )

        verb = "Would queue" if args.dry_run else "Queued"
        print(f"{verb} repair for {len(reference_ids)} reference ids.")

    except (httpx.HTTPError, FileNotFoundError) as exc:
        print(f"Invoking repair failed: {exc}")
