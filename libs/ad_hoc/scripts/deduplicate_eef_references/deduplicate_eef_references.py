# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "destiny-sdk>=0.11.0",
# ]
# ///

# ruff: noqa: T201

"""
Script to manually deduplicate EEF references.

Some EEF works have multiple study arms, represented as individual references in the
DESTINY repository. This script identifies and links duplicate references based on
all external identifiers matching.

```
uv run --script deduplicate_eef_references.py \
    --api-url ... \
    --azure-client-id ... \
    --azure-application-id ... \
    --dry-run
```

See also: https://github.com/destiny-evidence/destiny-repository/issues/570
"""

import argparse
from collections import defaultdict
from itertools import batched
from pathlib import Path
from uuid import UUID

from destiny_sdk.client import OAuthClient, OAuthMiddleware
from destiny_sdk.deduplication import (
    MakeDuplicateDecision,
    ManualDuplicateDetermination,
)
from destiny_sdk.identifiers import IdentifierLookup
from destiny_sdk.imports import ImportBatchRead, ImportRecordRead, ImportResultRead
from destiny_sdk.references import Reference
from pydantic import TypeAdapter

SCRIPT_DIR = Path(__file__).parent

EEF_SOURCE_PREFIX = "eef-eppi-review-export"

# API limitations
LOOKUP_REFERENCES_CHUNK_SIZE = 100
MAKE_DUPLICATE_DECISION_CHUNK_SIZE = 10


def get_eef_reference_ids(client: OAuthClient) -> list[UUID]:
    """Fetch EEF reference IDs by traversing import records via the API."""
    _client = client.get_client()

    response = _client.get("/imports/records/", timeout=30)
    response.raise_for_status()
    all_records = TypeAdapter(list[ImportRecordRead]).validate_json(response.content)
    eef_records = [
        r for r in all_records if r.source_name.startswith(EEF_SOURCE_PREFIX)
    ]

    reference_ids: list[UUID] = []
    for record in eef_records:
        response = _client.get(f"/imports/records/{record.id}/batches/", timeout=30)
        response.raise_for_status()
        batches = TypeAdapter(list[ImportBatchRead]).validate_json(response.content)
        for batch in batches:
            response = _client.get(
                f"/imports/records/{record.id}/batches/{batch.id}/results/",
                timeout=60,
            )
            response.raise_for_status()
            results = TypeAdapter(list[ImportResultRead]).validate_json(
                response.content
            )
            reference_ids.extend(r.reference_id for r in results if r.reference_id)

    return reference_ids


def get_references(
    client: OAuthClient,
    ids: list[UUID],
) -> list[Reference]:
    """Fetch structured references in chunks from the API given a list of IDs."""
    return [
        ref
        for chunk in batched(ids, LOOKUP_REFERENCES_CHUNK_SIZE)
        for ref in client.lookup([IdentifierLookup.from_identifier(i) for i in chunk])
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
        response = client.get_client().post(
            "/references/duplicate-decisions",
            json=[d.model_dump(mode="json") for d in chunk],
            timeout=60,
        )
        response.raise_for_status()
    print("Done.")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Deduplicate EEF references")
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

    print("Fetching EEF reference IDs from API...")
    ids = get_eef_reference_ids(client)
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
        duplicate_ids = {ref.id for group in duplicate_groups for ref in group[1:]}
        canonical_ids = [ref.id for ref in references if ref.id not in duplicate_ids]
        output_file = SCRIPT_DIR / f"canonical_ids_{args.azure_application_id}.txt"
        output_file.write_text(
            "\n".join(str(ref_id) for ref_id in canonical_ids) + "\n"
        )
        print(f"Wrote {len(canonical_ids)} canonical IDs to {output_file.name}")

        link_duplicates(client, duplicate_groups)

        print("Duplicate linking complete.")
