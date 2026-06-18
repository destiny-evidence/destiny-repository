"""Import references from a EPPI export file and write them to a .jsonl file."""

import argparse
import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from destiny_sdk.parsers.eppi_parser import EPPIParser


def parse_date(date_to_parse: str) -> datetime:
    """Parse a date string and return a datetime object."""
    try:
        return datetime.strptime(date_to_parse, "%Y-%m-%d %Z")  # noqa: DTZ007
    except ValueError as e:
        msg = (
            f"Could not parse --source-export-date {date_to_parse}, "
            "ensure in format YYYY-MM-DD TZ"
        )
        raise RuntimeError(msg) from e


TAG_PATTERN = re.compile(r"^[^/@]+/[^/@]+(@[^/@]+)?$")

DOMAIN_INCLUSION_TAG_SCHEME = "domain-inclusion"


def parse_tag(tag: str) -> str:
    """Validate a tag is in the format <scheme>/<label>[@<score>]."""
    if not TAG_PATTERN.match(tag):
        msg = (
            f"Could not parse --tags entry '{tag}', "
            "ensure in format <scheme>/<label>[@<score>], "
            "e.g. 'domain-inclusion/hpv@0.9'"
        )
        raise argparse.ArgumentTypeError(msg)
    return tag


def tag_scheme(tag: str) -> str:
    """Return the scheme (portion before the first slash) of a tag."""
    return tag.partition("/")[0]


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
        "--input-codec",
        "-ic",
        type=str,
        default="utf-8",
        help="The codec to decode the input file with, defaults to 'utf-8'",
    )

    arg_parser.add_argument(
        "--tags",
        nargs="+",
        type=parse_tag,
        default=[],
        help=(
            "A list of tags to add as annotation enhancements, each in the "
            "format <scheme>/<label>[@<score>], e.g. 'domain-inclusion/hpv@0.9'."
        ),
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
        "--include-eppi-id",
        action="store_true",
        help=(
            "Whether to include the EPPI ItemId as an OtherIdentifier "
            "on each reference"
        ),
    )

    arg_parser.add_argument(
        "--source-export-date",
        type=parse_date,
        default=None,
        help=(
            "Date and time when the source file was exported. "
            "Format: 'YEAR-MONTH-DAY TIMEZONE' "
            "For example '2023-12-2 UTC'"
        ),
    )

    arg_parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Description of the data to be stored as a raw enhancement",
    )

    arg_parser.add_argument(
        "--exclude-from-raw",
        nargs="+",
        default=["Abstract"],
        help=(
            "Any fields to exclude from the raw enhancements. "
            "Defaults to 'Abstract' as this is stored in its own enhancement."
        ),
    )

    args = arg_parser.parse_args()

    if args.include_eppi_id and not any(
        tag_scheme(tag) == DOMAIN_INCLUSION_TAG_SCHEME for tag in args.tags
    ):
        arg_parser.error(
            "At least one --tags entry must use the "
            f"'{DOMAIN_INCLUSION_TAG_SCHEME}' scheme when --include-eppi-id is set, "
            f"e.g. '{DOMAIN_INCLUSION_TAG_SCHEME}/hpv'."
        )

    input_path = Path(args.input)

    with input_path.open("rb") as f:
        file_bytes = f.read()
        checksum = base64.b64encode(hashlib.md5(file_bytes).digest()).decode("ascii")  # noqa: S324

    # errors='replace' is deliberate: EPPI exports occasionally contain CESU-8
    # surrogate pairs for non-BMP chars (e.g. mathematical italics) that strict
    # UTF-8 rejects. We'd rather degrade those rare chars to U+FFFD than fail
    # the whole import.
    data = json.loads(file_bytes.decode(args.input_codec, errors="replace"))

    eppi_parser = EPPIParser(
        tags=args.tags,
        include_raw_data=args.include_raw,
        include_eppi_id=args.include_eppi_id,
        source_export_date=args.source_export_date,
        data_description=args.description,
        raw_enhancement_excludes=args.exclude_from_raw,
    )

    references, failed_refs = eppi_parser.parse_data(
        data,
        source=args.source,
        robot_version=checksum,
    )

    with Path(args.output).open("w") as f:
        f.writelines(ref.to_jsonl() + "\n" for ref in references)

    failed_refs_path = args.output.removesuffix(".jsonl") + "-failures.json"

    with Path(failed_refs_path).open("w") as f:
        f.write(
            json.dumps(
                {"CodeSets": data.get("CodeSets"), "References": failed_refs},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
