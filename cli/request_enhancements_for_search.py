"""
A utility to trigger enhancement requests for references matching a search query.

Actions:
1. Search for the IDs of references matching the query
2. Create an enhancement request against a robot for the matched references

Authentication uses the CLI auth method (`CLIAuth`), and the search and
enhancement-request endpoints are called directly via httpx.
"""

# ruff: noqa: T201
import argparse
import sys
from datetime import UTC, datetime
from uuid import UUID

import httpx
from destiny_sdk.references import ReferenceIDSearchResult
from destiny_sdk.robots import EnhancementRequestIn

from app.core.config import Environment
from cli.auth import CLIAuth

from .config import get_settings


def search_all_references(client: httpx.Client, query: str) -> list[UUID]:
    """Fetch the IDs of all references matching the query in a single request."""
    response = client.get(
        "/v1/references/search/ids/",
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
        "/v1/enhancement-requests/",
        json=EnhancementRequestIn(
            robot_id=robot_id,
            reference_ids=reference_ids,
            source=source,
        ).model_dump(mode="json"),
    )
    response.raise_for_status()
    print(f"Created enhancement request {response.json()['id']}")


_PREVIEW_LIMIT = 10


def _preview(reference_ids: list[UUID], limit: int = _PREVIEW_LIMIT) -> None:
    """Print the first `limit` reference IDs."""
    for reference_id in reference_ids[:limit]:
        print(reference_id)
    if len(reference_ids) > limit:
        print("...")


_UUID_VERSION_7 = 7


def _parse_created_after(value: str) -> datetime:
    """Parse an ISO-8601 datetime arg, treating naive values as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid ISO-8601 datetime: {value!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _uuid7_created_at(reference_id: UUID) -> datetime:
    """Extract the creation time embedded in a UUID7's leading 48-bit ms timestamp."""
    return datetime.fromtimestamp((reference_id.int >> 80) / 1000, tz=UTC)


def _filter_created_after(
    reference_ids: list[UUID], created_after: datetime
) -> list[UUID]:
    """
    Keep only references created at or after `created_after`, per their UUID7 IDs.

    Errors if any ID is not a UUID7, since its creation time cannot be derived.
    """
    non_uuid7 = [rid for rid in reference_ids if rid.version != _UUID_VERSION_7]
    if non_uuid7:
        shown = non_uuid7[:_PREVIEW_LIMIT]
        ellipsis = ", ..." if len(non_uuid7) > _PREVIEW_LIMIT else ""
        msg = (
            f"--created-after cannot be applied: {len(non_uuid7)} matched reference(s) "
            "have non-UUID7 IDs whose creation time cannot be derived from the ID. "
            f"Offending IDs: {', '.join(str(rid) for rid in shown)}{ellipsis}"
        )
        raise ValueError(msg)
    return [rid for rid in reference_ids if _uuid7_created_at(rid) >= created_after]


def request_enhancements(  # noqa: PLR0913
    env: Environment,
    query: str,
    robot_id: UUID,
    source: str,
    exclude_reference_ids: set[UUID] | None = None,
    created_after: datetime | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Trigger an enhancement request for references matching a search query."""
    settings = get_settings(env)
    base_url = str(settings.destiny_repository_url).rstrip("/")
    exclude = exclude_reference_ids or set()

    with httpx.Client(base_url=base_url, auth=CLIAuth(env=env)) as client:
        all_reference_ids = search_all_references(client, query)
        reference_ids = [rid for rid in all_reference_ids if rid not in exclude]
        if exclude:
            print(f"{len(reference_ids)} references after exclusions.")

        if created_after is not None:
            reference_ids = _filter_created_after(reference_ids, created_after)
            print(
                f"{len(reference_ids)} references created after "
                f"{created_after.isoformat()}."
            )

        if not reference_ids:
            print("No references to enhance. Exiting.")
            return

        if dry_run:
            print(
                f"[DRY RUN] Would create an enhancement request against {env.value} "
                f"(robot_id={robot_id}) for {len(reference_ids)} references with IDs:"
            )
            _preview(reference_ids)
            return

        create_enhancement_request(client, robot_id, reference_ids, source)
        _preview(reference_ids)


def argument_parser() -> argparse.ArgumentParser:
    """Parse the environment, query, and enhancement request details."""
    parser = argparse.ArgumentParser(
        description=(
            "Triggers an enhancement request for references matching a search query."
        )
    )
    parser.add_argument(
        "-e",
        "--env",
        type=Environment,
        default=Environment.LOCAL,
        help="Environment to run the cli against.",
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
        "--created-after",
        type=_parse_created_after,
        default=None,
        help=(
            "Only request enhancements for references created at or after this "
            "ISO-8601 datetime, derived from the reference's UUID7 ID (e.g. "
            "'2026-01-01' or '2026-01-01T12:00:00+00:00'). Naive datetimes are "
            "treated as UTC. Errors if any matched reference has a non-UUID7 ID."
        ),
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
        request_enhancements(
            env=args.env,
            query=args.query,
            robot_id=args.robot_id,
            source=args.source,
            exclude_reference_ids=set(args.exclude_reference_ids),
            created_after=args.created_after,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)
    except httpx.HTTPError as exc:
        print(f"Enhancement request failed: {exc}")
        sys.exit(1)
