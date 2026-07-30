"""
A utility to trigger enhancement requests for references matching a search query.

Submits a single search-based enhancement request, which scans the full result set
server-side (no 10,000-result cap) and requests enhancements for every match, then
polls until the search has finished requesting them.
"""

# ruff: noqa: T201
import sys
import time
from uuid import UUID

import httpx
from destiny_sdk.client import OAuthClient
from destiny_sdk.robots import (
    EnhancementRequestSearchStatus,
    SearchEnhancementRequestRead,
)

from cli.client import ApiArgumentParser


def _print_progress(status: SearchEnhancementRequestRead) -> None:
    """Print a one-line snapshot of a search enhancement request's progress."""
    matched = status.n_matched if status.n_matched is not None else "?"
    print(
        f"search_status={status.search_status} "
        f"({status.n_enhancements_requested} of {matched} requested) | "
        f"request_status={status.request_status} {status.enhancement_status_counts}"
    )


def poll_until_search_complete(
    client: OAuthClient,
    request_id: UUID,
    poll_interval: float = 30,
) -> SearchEnhancementRequestRead:
    """Poll until the search phase stops progressing (all requested, or failed)."""
    print(f"Polling search enhancement request {request_id}...")
    terminal = EnhancementRequestSearchStatus.get_terminal_statuses()
    while True:
        status = client.get_search_enhancement_request(request_id)
        _print_progress(status)
        if status.search_status in terminal:
            return status
        time.sleep(poll_interval)


def request_enhancements(  # noqa: PLR0913
    client: OAuthClient,
    query: str,
    robot_id: UUID,
    source: str,
    *,
    dry_run: bool = False,
    poll_interval: float = 30,
) -> None:
    """Trigger an enhancement request for references matching a search query."""
    if dry_run:
        total = client.request_search_enhancement(
            robot_id=robot_id,
            search_query=query,
            source=source,
            dry_run=True,
        )
        print(
            f"[DRY RUN] {total.count} references match. "
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

    status = poll_until_search_complete(client, request.id, poll_interval)
    if status.search_status is EnhancementRequestSearchStatus.FAILED:
        print(f"Search failed: {status.error}")
        sys.exit(1)
    print(
        f"Search complete: {status.n_enhancements_requested} enhancements requested. "
        "The robot fulfils these in the background; keep polling "
        f"GET /enhancement-requests/search/{request.id}/ to watch request_status."
    )


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
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30,
        help="Seconds to wait between search status checks (default 30).",
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
                poll_interval=args.poll_interval,
            )
    except httpx.HTTPError as exc:
        print(f"Enhancement request failed: {exc}")
        sys.exit(1)
