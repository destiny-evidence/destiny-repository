"""
A utility to resolve OpenAlex works to the references that already hold them.

Ingestors that enhance existing references need a lookup mapping each OpenAlex work
to its reference id in the target environment. This pulls that mapping from a
repository environment and writes it as JSONL, one `Reference` per line, which is
the shape those ingestors read.

Reference ids differ per environment, and a lookup built against the wrong one
matches nothing without raising, so name the output for the environment and date::

    uv run python -m cli.lookup_openalex_references --env production \
        --identifier-file openalex-matches.csv --column openalex_id \
        --output production-lookup-2026-09-28.jsonl

Without ``--column`` each file holds one work id per line. Work ids may be bare
(`W3121659249`), lookup-prefixed (`open_alex:W3121659249`) or the full OpenAlex URL.

See also: https://github.com/destiny-evidence/destiny-repository/issues/555
"""

# ruff: noqa: T201
import csv
import re
from collections.abc import Iterable
from itertools import batched
from pathlib import Path

from destiny_sdk.client import OAuthClient
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.references import Reference

from cli.client import ApiArgumentParser

# API limitation: max_lookup_reference_query_length
LOOKUP_REFERENCES_CHUNK_SIZE = 100

OPENALEX_IDENTIFIER_PREFIX = f"{ExternalIdentifierType.OPEN_ALEX.value}:"
OPENALEX_URL_PREFIX = "https://openalex.org/"
# Anchored: an unanchored pattern accepts anything containing a work id.
WORK_ID_PATTERN = re.compile(r"W\d+")


def normalise_work_id(raw: str) -> str:
    """Reduce any accepted OpenAlex work form to the bare id the repository stores."""
    value = (
        raw.strip()
        .removeprefix(OPENALEX_IDENTIFIER_PREFIX)
        .removeprefix(OPENALEX_URL_PREFIX)
    )
    if not WORK_ID_PATTERN.fullmatch(value):
        msg = f"{raw.strip()!r} is not an OpenAlex work id"
        raise ValueError(msg)
    return value


def read_column(path: Path, column: str) -> list[str]:
    """Read one column of a CSV, skipping blank cells."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            msg = f"{path} has no column {column!r}"
            raise ValueError(msg)
        return [row[column] for row in reader if row[column].strip()]


def load_work_ids(paths: Iterable[Path], column: str | None = None) -> list[str]:
    """Read work ids from files, normalised and deduplicated, in first-seen order."""
    work_ids = [
        normalise_work_id(value)
        for path in paths
        for value in (
            read_column(path, column)
            if column
            else path.read_text(encoding="utf-8").splitlines()
        )
        if value.strip()
    ]
    return list(dict.fromkeys(work_ids))


def unresolved_work_ids(requested: list[str], references: list[Reference]) -> list[str]:
    """
    Return the requested works that no returned reference claims.

    A short lookup otherwise reads downstream as a work the repository lacks.
    """
    resolved = {
        identifier.identifier
        for reference in references
        for identifier in reference.identifiers or []
        if identifier.identifier_type == ExternalIdentifierType.OPEN_ALEX
    }
    return [work_id for work_id in requested if work_id not in resolved]


def fetch_references(client: OAuthClient, work_ids: list[str]) -> list[Reference]:
    """Look up references in chunks the API will accept."""
    references: list[Reference] = []
    for chunk in batched(work_ids, LOOKUP_REFERENCES_CHUNK_SIZE):
        found = client.lookup(
            [f"{OPENALEX_IDENTIFIER_PREFIX}{work_id}" for work_id in chunk]
        )
        print(f"  {len(chunk)} requested, {len(found)} returned")
        references.extend(found)
    return references


def write_references(path: Path, references: Iterable[Reference]) -> None:
    """Write references as JSONL, one per line."""
    path.write_text(
        "".join(reference.to_jsonl() + "\n" for reference in references),
        encoding="utf-8",
    )


def argument_parser() -> ApiArgumentParser:
    """Parse the environment, the work id files, and where to write the lookup."""
    parser = ApiArgumentParser(
        description="Resolve OpenAlex works to repository reference records."
    )
    parser.add_argument(
        "--identifier-file",
        required=True,
        action="append",
        dest="identifier_files",
        type=Path,
        help="File of work ids, one per line, or a CSV with --column. Repeatable.",
    )
    parser.add_argument(
        "--column",
        help="Read work ids from this column of each identifier file, as CSV.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the lookup to, as .jsonl of `Reference`s.",
    )
    return parser


if __name__ == "__main__":
    args = argument_parser().parse_args()

    work_ids = load_work_ids(args.identifier_files, args.column)
    print(f"{len(work_ids)} distinct work(s) to resolve against {args.env}.")

    references = fetch_references(args.oauth_client, work_ids)
    write_references(args.output, references)
    print(f"Wrote {len(references)} reference(s) to {args.output}")

    if unresolved := unresolved_work_ids(work_ids, references):
        print(f"{len(unresolved)} work(s) did not resolve: {', '.join(unresolved)}")
