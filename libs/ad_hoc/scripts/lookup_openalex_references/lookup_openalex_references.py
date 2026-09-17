# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "destiny-sdk>=0.16.1",
# ]
# ///

# ruff: noqa: T201

"""
Script to resolve OpenAlex works to the references that already hold them.

Ingestors that enhance existing references need a lookup mapping each OpenAlex work
to its reference id in the target environment. This pulls that mapping from a
repository environment and writes it as JSONL, one `Reference` per line, which is
the shape those ingestors read.

Reference ids differ per environment, and a lookup built against the wrong one
matches nothing without raising, so the output filename carries the environment and
the date it was taken.

```
uv run --script lookup_openalex_references.py \
    --env production \
    --identifier-file round-one-wids.txt \
    --identifier-file stage-two-identifiers.txt
```

Work ids may be bare (`W3121659249`), lookup-prefixed (`open_alex:W3121659249`) or
the full OpenAlex URL. All three appear in the files this reads.

Authentication is the SDK default for the environment, a Keycloak public client, so
the first request opens a browser. The token is held in memory for the life of the
process, so the login and the whole pull happen in one run.

See also: https://github.com/destiny-evidence/destiny-repository/issues/555
"""

import argparse
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path

from destiny_sdk.client import OAuthClient
from destiny_sdk.identifiers import ExternalIdentifierType
from destiny_sdk.references import Reference

SCRIPT_DIR = Path(__file__).parent

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


def load_work_ids(paths: Iterable[Path]) -> list[str]:
    """Read work ids from files, normalised and deduplicated, in first-seen order."""
    work_ids = [
        normalise_work_id(line)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
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


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Resolve OpenAlex works to repository reference records"
    )
    arg_parser.add_argument(
        "--env",
        required=True,
        choices=["development", "staging", "production"],
        help="Repository environment to resolve against",
    )
    arg_parser.add_argument(
        "--identifier-file",
        required=True,
        action="append",
        dest="identifier_files",
        type=Path,
        help="File of OpenAlex work ids, one per line. Repeatable.",
    )
    arg_parser.add_argument(
        "--output",
        type=Path,
        help="Output path. Defaults to <env>-lookup-<date>.jsonl beside this script.",
    )
    args = arg_parser.parse_args()

    work_ids = load_work_ids(args.identifier_files)
    print(f"{len(work_ids)} distinct work(s) to resolve against {args.env}.")

    client = OAuthClient(env=args.env)
    references = fetch_references(client, work_ids)

    output_file = args.output or SCRIPT_DIR / (
        f"{args.env}-lookup-{datetime.now(UTC):%Y-%m-%d}.jsonl"
    )
    output_file.write_text(
        "".join(
            reference.model_dump_json(exclude_none=True) + "\n"
            for reference in references
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(references)} reference(s) to {output_file.name}")

    if unresolved := unresolved_work_ids(work_ids, references):
        print(f"{len(unresolved)} work(s) did not resolve: {', '.join(unresolved)}")
