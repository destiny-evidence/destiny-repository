"""
A utility to trigger enhancement requests for references matching a search query.

Submits a single search-based enhancement request, which scans the full result set
server-side (no 10,000-result cap) and requests enhancements for every match.
"""

# ruff: noqa: T201
import sys
from uuid import UUID

import httpx
from destiny_sdk.client import OAuthClient

from cli.client import ApiArgumentParser


def request_enhancements(
    client: OAuthClient,
    query: str,
    robot_id: UUID,
    source: str,
    *,
    dry_run: bool = False,
) -> None:
    """Trigger an enhancement request for references matching a search query."""
    if dry_run:
        total = client.request_search_enhancement(
            robot_id=robot_id,
            search_query=query,
            source=source,
            dry_run=True,
        )
        qualifier = " (lower bound)" if total.is_lower_bound else ""
        print(
            f"[DRY RUN] {total.count}{qualifier} references match. "
            "No enhancement request was created."
        )
        return

    request = client.request_search_enhancement(
        robot_id=robot_id,
        search_query=query,
        source=source,
    )
    print(
        f"Created search enhancement request {request.id} "
        f"(search_status={request.search_status})."
    )
    print(f"Poll status with: GET /enhancement-requests/search/{request.id}/")


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
        "--dry-run",
        action="store_true",
        help="Report the number of matching references without creating a request.",
    )
    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with args.client:
            request_enhancements(
                client=args.oauth_client,
                query=args.query,
                robot_id=args.robot_id,
                source=args.source,
                dry_run=args.dry_run,
            )
    except httpx.HTTPError as exc:
        print(f"Enhancement request failed: {exc}")
        sys.exit(1)
