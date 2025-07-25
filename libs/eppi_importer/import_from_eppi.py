"""Import references from a EPPI export file and write them to a .jsonl file."""

import argparse
from pathlib import Path

from destiny_sdk.parsers.eppi_parser import parse_file


def main() -> None:
    """Import references from a EPPI export and write them to a .jsonl file."""
    parser = argparse.ArgumentParser(
        description="Import references from a EPPI export file."
    )
    parser.add_argument(
        "--input", "-i", type=str, required=True, help="Input EPPI export filename"
    )
    parser.add_argument(
        "--output", "-o", type=str, required=True, help="Output .jsonl filename"
    )
    parser.add_argument(
        "--tags",
        nargs="+",
        default=[],
        help="A list of tags to add as annotation enhancements.",
    )
    args = parser.parse_args()

    references = parse_file(Path(args.input), tags=args.tags)

    with Path(args.output).open("w") as f:
        for ref in references:
            f.write(ref.to_jsonl() + "\n")


if __name__ == "__main__":
    main()
