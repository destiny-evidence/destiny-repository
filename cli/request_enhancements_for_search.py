"""
A utility to trigger enhancement requests for references matching a search query.

Actions:
1. Search for the IDs of references matching the query
2. Create an enhancement request against a robot for the matched references
"""

# ruff: noqa: T201
import sys
from uuid import UUID

import httpx
from destiny_sdk.references import ReferenceIDSearchResult
from destiny_sdk.robots import EnhancementRequestIn

from cli.client import ApiArgumentParser


def search_all_references(client: httpx.Client, query: str) -> list[UUID]:
    """Fetch the IDs of all references matching the query in a single request."""
    response = client.get(
        "/references/search/ids/",
        params={"q": query},
    )
    response.raise_for_status()
    result = ReferenceIDSearchResult.model_validate(response.json())
    if result.total.is_lower_bound:
        print(
            f"Warning: more than {len(result.reference_ids)} references match; "
            "only the first 10,000 are returned."
        )
    print(
        f"Found {len(result.reference_ids)} reference IDs "
        f"(total {result.total.count})."
    )
    return result.reference_ids


def create_enhancement_request(
    client: httpx.Client,
    robot_id: UUID,
    reference_ids: list[UUID],
    source: str,
) -> None:
    """POST an enhancement request for the given references."""
    print(f"Creating enhancement request for {len(reference_ids)} references...")
    response = client.post(
        "/enhancement-requests/",
        json=EnhancementRequestIn(
            robot_id=robot_id,
            reference_ids=reference_ids,
            source=source,
        ).model_dump(mode="json"),
    )
    response.raise_for_status()
    print(f"Created enhancement request {response.json()['id']}")


def _preview(reference_ids: list[UUID], limit: int = 10) -> None:
    """Print the first `limit` reference IDs."""
    for reference_id in reference_ids[:limit]:
        print(reference_id)
    if len(reference_ids) > limit:
        print("...")


def request_enhancements(  # noqa: PLR0913
    client: httpx.Client,
    query: str,
    robot_id: UUID,
    source: str,
    exclude_reference_ids: set[UUID] | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Trigger an enhancement request for references matching a search query."""
    exclude = exclude_reference_ids or set()

    all_reference_ids = search_all_references(client, query)
    reference_ids = [rid for rid in all_reference_ids if rid not in exclude]
    if exclude:
        print(f"{len(reference_ids)} references after exclusions.")

    if not reference_ids:
        print("No references to enhance. Exiting.")
        return

    if dry_run:
        print(
            f"[DRY RUN] Would create an enhancement request against "
            f"{client.base_url} (robot_id={robot_id}) for {len(reference_ids)} "
            "references with IDs:"
        )
        _preview(reference_ids)
        return

    create_enhancement_request(client, robot_id, reference_ids, source)
    _preview(reference_ids)


def argument_parser() -> ApiArgumentParser:
    """Parse the environment, query, and enhancement request details."""
    parser = ApiArgumentParser(
        description=(
            "Triggers an enhancement request for references matching a search query."
        )
    )
    parser.add_argument(
        "-q",
        "--query",
        required=True,
        help="Lucene search query (e.g. 'annotations:\"domain-inclusion/hpv\"').",
    )
    parser.add_argument(
        "--robot-id",
        type=UUID,
        required=True,
        help="ID of the robot to handle the enhancement.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source identifier for the enhancement request.",
    )
    parser.add_argument(
        "--exclude-reference-id",
        action="append",
        type=UUID,
        default=[],
        dest="exclude_reference_ids",
        help="Reference ID to exclude (repeatable).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be requested without creating an enhancement request.",
    )
    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with args.client as client:
            request_enhancements(
                client=client,
                query=args.query,
                robot_id=args.robot_id,
                source=args.source,
                exclude_reference_ids=set(args.exclude_reference_ids),
                dry_run=args.dry_run,
            )
    except httpx.HTTPError as exc:
        print(f"Enhancement request failed: {exc}")
        sys.exit(1)
