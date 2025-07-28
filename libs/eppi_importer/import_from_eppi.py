"""Import references from a EPPI export file and write them to a .jsonl file."""

import argparse
import json
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
    args = arg_parser.parse_args()

    with Path(args.input).open() as f:
        data = json.load(f)
    eppi_parser = EPPIParser(tags=args.tags)
    references = eppi_parser.parse_data(data)

    with Path(args.output).open("w") as f:
        for ref in references:
            f.write(ref.to_jsonl() + "\n")


if __name__ == "__main__":
    main()
