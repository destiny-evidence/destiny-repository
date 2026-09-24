"""
A utility to parse an EPPI export into raw enhancements to add to existing references.

Each reference in the export must carry the id of the destiny reference it codes in
its URL field, e.g.
https://data.evidence-repository.org/esea/references/019f880e-2c39-7138-a387-221808f02d98

References are verified to exist in the environment they're run against, unless
``--skip-verification`` is passed. If the export contains a missing reference the
parsing fails.

Warnings are raised for references that have title mismatches.

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
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
from destiny_sdk.enhancements import Enhancement, EnhancementType
from destiny_sdk.parsers.eppi_parser import EPPIParser, load_eppi_export
from destiny_sdk.parsers.exceptions import ReferenceIdNotFoundError
from destiny_sdk.references import Reference
from fastapi import status

from cli.client import ApiArgumentParser


def verify_one_enhancement_per_reference(
    enhancements: Sequence[Enhancement],
) -> None:
    """Check no reference is enhanced twice, reporting every duplicate."""
    reference_counts = Counter(enhancement.reference_id for enhancement in enhancements)
    duplicated = {
        reference_id: count
        for reference_id, count in reference_counts.items()
        if count > 1
    }

    if duplicated:
        msg = (
            "Duplicate enhancements for the same reference id are not allowed. "
            f"{len(duplicated)} reference id(s) are enhanced more than once: "
            + ", ".join(
                f"{reference_id} ({count} enhancements)"
                for reference_id, count in duplicated.items()
            )
            + "."
        )
        raise ValueError(msg)


def _comparable_title(title: str) -> str:
    """Fold the case and whitespace EPPI and the repository differ in incidentally."""
    return " ".join(title.split()).casefold()


def exported_title(enhancement: Enhancement) -> str | None:
    """Read the EPPI title from a raw enhancement, unless it was excluded."""
    if enhancement.content.enhancement_type is not EnhancementType.RAW:
        return None
    title = enhancement.content.data.get("Title")
    return title if isinstance(title, str) and title.strip() else None


def repository_titles(reference: Reference) -> list[str]:
    """Every title the repository holds for a reference, one per contributing source."""
    return [
        enhancement.content.title
        for enhancement in reference.enhancements or []
        if enhancement.content.enhancement_type is EnhancementType.BIBLIOGRAPHIC
        and enhancement.content.title
    ]


def report_title_mismatches(
    mismatched: list[tuple[UUID, str, list[str]]], incomparable: list[UUID]
) -> None:
    """Warn about titles that disagree, without failing the run."""
    if mismatched:
        print(
            f"WARNING: {len(mismatched)} reference(s) have a title differing from "
            "the repository:"
        )
        for reference_id, exported, repository in mismatched:
            print(f"  {reference_id}")
            print(f"    export:     {exported!r}")
            print(f"    repository: {', '.join(repr(t) for t in repository)}")

    if incomparable:
        print(f"{len(incomparable)} reference(s) had no title to compare.")


def verify_references(
    client: httpx.Client, enhancements: Sequence[Enhancement]
) -> None:
    """
    Check each reference exists, reporting every missing one at once.

    Titles that disagree with the repository's are warned about rather than raised.
    """
    print(f"Verifying {len(enhancements)} reference(s) exist...")
    missing: list[UUID] = []
    mismatched: list[tuple[UUID, str, list[str]]] = []
    incomparable: list[UUID] = []

    for enhancement in enhancements:
        reference_id = enhancement.reference_id
        response = client.get(f"/references/{reference_id}/")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            missing.append(reference_id)
            continue
        response.raise_for_status()

        exported = exported_title(enhancement)
        repository = repository_titles(Reference.model_validate(response.json()))
        if not exported or not repository:
            incomparable.append(reference_id)
        elif not any(
            _comparable_title(title) == _comparable_title(exported)
            for title in repository
        ):
            mismatched.append((reference_id, exported, repository))

    if missing:
        msg = (
            f"{len(missing)} reference(s) in the export are not in the repository: "
            f"{', '.join(str(reference_id) for reference_id in missing)}."
        )
        raise ValueError(msg)

    report_title_mismatches(mismatched, incomparable)


def parse_eppi_enhancements(args: argparse.Namespace) -> None:
    """
    Parse the export, check its references exist, and write the enhancements.

    Raises ValueError if there is more than one enhancement for the same reference
    or if any references do not exist.
    """
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

    verify_one_enhancement_per_reference(enhancements)

    if args.skip_verification:
        print("Skipping verification that the references exist.")
    else:
        with args.client as client:
            verify_references(client, enhancements)

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
            "Defaults to 'Abstract' as we expect to already have abstracts for"
            "references we're adding raw enhancements to."
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
