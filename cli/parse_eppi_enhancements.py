"""
A utility to parse an EPPI export into raw enhancements to add to existing references.

Each reference in the export must carry the id of the destiny reference it codes in
its URL field, e.g.
https://data.evidence-repository.org/esea/references/019f880e-2c39-7138-a387-221808f02d98

References are verified to exist in the environment they're run against, unless
``--skip-verification`` is passed. If the export contains a missing reference the
parsing fails.

Parse an export into Enhancements for existing references::

    uv run python -m cli.parse_eppi_enhancements --env staging \
        --input eef-coding-export.json \
        --output eef-coding-enhancements.jsonl \
        --source eef-eppi-review \
        --description 'EEF additional coding request, Sept 2026' \
        --source-export-date 2026-09-16

These can then be added to the references with the cli/add_static_enhancements utility.
"""

# ruff: noqa: T201
import argparse
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
from destiny_sdk.parsers.eppi_parser import EPPIParser, load_eppi_export
from destiny_sdk.parsers.exceptions import ReferenceIdNotFoundError
from fastapi import status

from cli.client import ApiArgumentParser


def verify_references(client: httpx.Client, reference_ids: set[UUID]) -> None:
    """Check each reference exists, reporting every missing one at once."""
    print(f"Verifying {len(reference_ids)} reference(s) exist...")
    missing: list[UUID] = []
    for reference_id in sorted(reference_ids):
        response = client.get(f"/references/{reference_id}/")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            missing.append(reference_id)
            continue
        response.raise_for_status()

    if missing:
        msg = (
            f"{len(missing)} reference(s) in the export are not in the repository: "
            f"{', '.join(str(reference_id) for reference_id in missing)}."
        )
        raise ValueError(msg)


def parse_eppi_enhancements(args: argparse.Namespace) -> None:
    """Parse the export, check its references exist, and write the enhancements."""
    data, checksum = load_eppi_export(Path(args.input), args.input_codec)

    eppi_parser = EPPIParser(
        include_raw_data=True,
        source_export_date=args.source_export_date,
        data_description=args.description,
        raw_enhancement_excludes=args.exclude_from_raw,
    )
    enhancements = eppi_parser.parse_enhancements(
        data,
        source=args.source,
        robot_version=checksum,
    )
    print(f"Parsed {len(enhancements)} enhancement(s) from {args.input}.")

    if args.skip_verification:
        print("Skipping verification that the references exist.")
    else:
        with args.client as client:
            verify_references(
                client,
                {enhancement.reference_id for enhancement in enhancements},
            )

    with Path(args.output).open("w") as f:
        f.writelines(enhancement.to_jsonl() + "\n" for enhancement in enhancements)
    print(f"Wrote {len(enhancements)} enhancement(s) to {args.output}.")


def argument_parser() -> ApiArgumentParser:
    """Parse the export to read, the enhancements to write, and their provenance."""
    parser = ApiArgumentParser(
        description=(
            "Parses an EPPI export into raw enhancements for existing references."
        )
    )

    parser.add_argument(
        "--input", "-i", required=True, help="Input EPPI export filename."
    )
    parser.add_argument("--output", "-o", required=True, help="Output .jsonl filename.")
    parser.add_argument(
        "--input-codec",
        "-ic",
        default="utf-8",
        help="The codec to decode the input file with, defaults to 'utf-8'.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source identifier for provenance (e.g., eef-eppi-review).",
    )
    parser.add_argument(
        "--description",
        required=True,
        help="Description of the data to be stored as a raw enhancement.",
    )
    parser.add_argument(
        "--source-export-date",
        type=datetime.fromisoformat,
        required=True,
        help=(
            "Date the export was taken from EPPI, in ISO 8601 format, "
            "e.g. '2026-09-16' or '2026-09-16T09:30:00+00:00'."
        ),
    )
    parser.add_argument(
        "--exclude-from-raw",
        nargs="+",
        default=["Abstract"],
        help=(
            "Any fields to exclude from the raw enhancements. "
            "Defaults to 'Abstract' as this is stored in its own enhancement."
        ),
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        default=False,
        help=(
            "Write the enhancements without checking their references exist. "
            "Defaults to false."
        ),
    )
    return parser


if __name__ == "__main__":
    try:
        parse_eppi_enhancements(argument_parser().parse_args())
    except (
        ReferenceIdNotFoundError,
        ValueError,
        httpx.HTTPError,
        OSError,
    ) as exc:
        print(f"Parsing EPPI enhancements failed: {exc}")
        sys.exit(1)
