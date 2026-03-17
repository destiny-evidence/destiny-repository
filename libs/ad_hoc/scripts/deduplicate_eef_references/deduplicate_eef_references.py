# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "destiny-sdk>=0.11.0",
# ]
# ///

# ruff: noqa: S603, S607, T201

"""
Script to manually deduplicate EEF references.

Some EEF works have multiple study arms, represented as individual references in the
DESTINY repository. This script identifies and links duplicate references based on
all external identifiers matching.

DB reads are performed by exec'ing a Python script into a running container
app, which has network access to the database and the necessary packages
(asyncpg, azure-identity) already installed. API writes use the public URL.

```
uv run --script deduplicate_eef_references.py \
    --environment development \
    --api-url ... \
    --azure-client-id ... \
    --azure-application-id ... \
    --dry-run
```

See also: https://github.com/destiny-evidence/destiny-repository/issues/570
"""

import argparse
import base64
import os
import pty
import subprocess
from collections import defaultdict
from itertools import batched
from pathlib import Path

from destiny_sdk.client import OAuthClient, OAuthMiddleware
from destiny_sdk.deduplication import (
    MakeDuplicateDecision,
    ManualDuplicateDetermination,
)
from destiny_sdk.identifiers import IdentifierLookup
from destiny_sdk.references import Reference

REMOTE_QUERY_SCRIPT = Path(__file__).parent / "_remote_get_eef_reference_ids.py"

# API limitations
LOOKUP_REFERENCES_CHUNK_SIZE = 100
MAKE_DUPLICATE_DECISION_CHUNK_SIZE = 10


def get_eef_reference_ids(environment: str) -> list[str]:
    """Fetch EEF reference IDs by exec'ing a Python script into the container."""
    app_name = f"destiny-repository-{environment[:4]}-app"
    resource_group = f"rg-destiny-repository-{environment}"
    container = subprocess.run(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            app_name,
            "--resource-group",
            resource_group,
            "--query",
            "properties.template.containers[0].name",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # az containerapp exec splits --command on spaces (direct exec, no shell),
    # so we use python3 -c with a space-free expression to bootstrap the
    # remote script. exec also requires stdin to be a TTY.
    encoded = base64.b64encode(REMOTE_QUERY_SCRIPT.read_bytes()).decode()
    bootstrap = (
        f"exec(compile(__import__('base64').b64decode('{encoded}')"
        ",'<remote>','exec'),{'__name__':'__main__'})"
    )
    primary_fd, replica_fd = pty.openpty()
    try:
        result = subprocess.run(
            [
                "az",
                "containerapp",
                "exec",
                "--name",
                app_name,
                "--resource-group",
                resource_group,
                "--container",
                container,
                "--command",
                f"python3 -c {bootstrap}",
            ],
            stdin=replica_fd,
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        os.close(replica_fd)
        os.close(primary_fd)

    return parse_reference_ids(result.stdout)


def parse_reference_ids(output: str) -> list[str]:
    """Extract reference IDs from delimited remote script output."""
    start = output.index("---BEGIN_RESULTS---") + len("---BEGIN_RESULTS---") + 1
    end = output.index("---END_RESULTS---")
    return [line.strip() for line in output[start:end].splitlines() if line.strip()]


def get_references(
    client: OAuthClient,
    ids: list[str],
) -> list[Reference]:
    """Fetch structured references in chunks from the API given a list of IDs."""
    return [
        ref
        for chunk in batched(ids, LOOKUP_REFERENCES_CHUNK_SIZE)
        for ref in client.lookup(chunk)
    ]


def group_references(
    references: list[Reference],
) -> list[list[Reference]]:
    """Group references that share an identical set of identifiers."""
    groups: dict[frozenset[str], list[Reference]] = defaultdict(list)
    for reference in references:
        if not reference.identifiers:
            continue
        # Use existing serializer to nicely handle "other" identifiers :)
        key = frozenset(
            IdentifierLookup.from_identifier(identifier).serialize()
            for identifier in reference.identifiers
        )
        groups[key].append(reference)
    return [group for group in groups.values() if len(group) > 1]


def _build_decisions(group: list[Reference]) -> list[MakeDuplicateDecision]:
    """Build duplicate decisions for a group, first reference becomes canonical."""
    canonical, *duplicates = group
    return [
        MakeDuplicateDecision(
            reference_id=canonical.id,
            duplicate_determination=ManualDuplicateDetermination.CANONICAL,
        ),
        *(
            MakeDuplicateDecision(
                reference_id=ref.id,
                duplicate_determination=ManualDuplicateDetermination.DUPLICATE,
                canonical_reference_id=canonical.id,
            )
            for ref in duplicates
        ),
    ]


def link_duplicates(
    client: OAuthClient,
    reference_groups: list[list[Reference]],
) -> None:
    """Link duplicate references together."""
    decisions = [
        decision for group in reference_groups for decision in _build_decisions(group)
    ]
    print(f"Sending {len(decisions)} decisions...")
    chunks = list(batched(decisions, MAKE_DUPLICATE_DECISION_CHUNK_SIZE))
    for i, chunk in enumerate(chunks, 1):
        print(f"  Chunk {i}/{len(chunks)} ({len(chunk)} decisions)")
        client.get_client().post(
            "/references/duplicate-decisions",
            json=[d.model_dump(mode="json") for d in chunk],
            timeout=60,
        )
    print("Done.")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Deduplicate EEF references")
    arg_parser.add_argument(
        "--environment",
        required=True,
        help="Environment to run the script against",
        choices=["development", "staging", "production"],
    )
    arg_parser.add_argument(
        "--api-url",
        required=True,
        help="Public API URL (e.g. https://destiny-repository.example.com)",
    )
    arg_parser.add_argument(
        "--azure-client-id",
        required=True,
        help="Azure auth client ID (destiny_repository_auth)",
    )
    arg_parser.add_argument(
        "--azure-application-id",
        required=True,
        help="Azure application ID for the Destiny API",
    )
    arg_parser.add_argument(
        "--azure-login-url",
        default="https://login.microsoftonline.com/f870e5ae-5521-4a94-b9ff-cdde7d36dd35",
        help="Azure login URL",
    )
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print duplicates without linking them",
    )
    args = arg_parser.parse_args()

    client = OAuthClient(
        base_url=args.api_url,
        auth=OAuthMiddleware(
            azure_client_id=args.azure_client_id,
            azure_application_id=args.azure_application_id,
            azure_login_url=args.azure_login_url,
        ),
    )

    print(f"Fetching EEF reference IDs from {args.environment}...")
    ids = get_eef_reference_ids(args.environment)
    print(f"Found {len(ids)} EEF references.")

    print("Looking up references from API...")
    references = get_references(client, ids)
    print(f"Fetched {len(references)} references.")

    duplicate_groups = group_references(references)
    print(f"Found {len(duplicate_groups)} duplicate groups.")
    for group in duplicate_groups:
        canonical, *duplicates = group
        print(f"  {canonical.id}: {len(duplicates)} duplicate(s)")

    if args.dry_run:
        print("Dry run — no changes made.")
    else:
        link_duplicates(client, duplicate_groups)
        print("Duplicate linking complete.")
