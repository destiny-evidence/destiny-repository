"""Import references from a EPPI export file and write them to a .jsonl file."""

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from destiny_sdk.parsers.eppi_parser import EPPIParser


def main() -> None:
    """Import references from a EPPI export and write them to a .jsonl file."""
    arg_parser = argparse.ArgumentParser(
        description="Import references from a EPPI export file."
    )
    arg_parser.add_argument(
        "--input", "-i", type=str, required=True, help="Input EPPI export filename"
    )
    arg_parser.add_argument(
        "--output", "-o", type=str, required=True, help="Output .jsonl filename"
    )
    arg_parser.add_argument(
        "--tags",
        nargs="+",
        default=[],
        help="A list of tags to add as annotation enhancements.",
    )
    arg_parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Source identifier for provenance (e.g., alive-hpv-partnership)",
    )

    arg_parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Whether to include raw data enhancements for the import",
    )

    arg_parser.add_argument(
        "--source-export-timestamp",
        type=int,
        default=None,
        help="Timestamp of when the source file was exported",
    )

    arg_parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Description of the data to be stored as a raw enhancement",
    )

    arg_parser.add_argument(
        "--codeset-id",
        type=int,
        default=None,
        help="The codeset id of the attributes on the incoming references.",
    )

    args = arg_parser.parse_args()

    input_path = Path(args.input)

    with input_path.open("rb") as f:
        file_bytes = f.read()
        checksum = base64.b64encode(hashlib.md5(file_bytes).digest()).decode("ascii")  # noqa: S324

    data = json.loads(file_bytes.decode("utf-8"))

    source_export_date = (
        datetime.fromtimestamp(args.source_export_timestamp, tz=UTC)
        if args.source_export_timestamp
        else None
    )

    metadata = {"codeset_id": args.codeset_id} if args.codeset_id else None

    eppi_parser = EPPIParser(
        tags=args.tags,
        include_raw_data=args.include_raw,
        source_export_date=source_export_date,
        data_description=args.description,
        raw_enhancement_metadata=metadata,
    )

    references = eppi_parser.parse_data(
        data,
        source=args.source,
        robot_version=checksum,
    )

    with Path(args.output).open("w") as f:
        f.writelines(ref.to_jsonl() + "\n" for ref in references)


if __name__ == "__main__":
    main()
