r"""
A utility to add a static list of enhancements to references.

This utility:
- Accepts either:
    - a .jsonl file of `Enhancement`s
    - a text file of reference ids and a single
      `destiny_sdk.enhancements.EnhancementFileInput` to apply to each of them
- Requests enhancements from the repository for each unique reference_id
- Acts as a robot to add the enhancements to the references in the repository
- Prints the results of the original enhancement request

Add an enhancement per reference, with a robot to write them::

    uv run python -m cli.add_static_enhancements --env staging \
        --enhancement-file enhancements.jsonl \
        --create-robot 'your-project-static-enhancement-robot'

Tag those same references, reusing a robot::

    uv run python -m cli.add_static_enhancements --env staging \
        --reference-id-file references.txt \
        --enhancement '{"source": "your-project-initial-hydration",
            "visibility": "public", "content": {"enhancement_type": "annotation",
            "annotations": [{"annotation_type": "boolean",
            "scheme": "domain-inclusion", "label": "your-project", "value": true}]}}' \
        --robot-id 019ec8b0-9173-76f0-9d09-b7bdf4e31047

The caller must have robot.writer and enhancement_request.writer permissions.
"""

# ruff: noqa: T201
import argparse
import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

import httpx
from destiny_sdk.client import RobotClient
from destiny_sdk.enhancements import Enhancement, EnhancementFileInput, EnhancementType
from destiny_sdk.robots import (
    EnhancementRequestIn,
    EnhancementRequestRead,
    EnhancementRequestStatus,
    ProvisionedRobot,
    Robot,
    RobotEnhancementBatch,
    RobotEnhancementBatchResult,
    RobotEntitlement,
    RobotIn,
)
from pydantic import HttpUrl, ValidationError

from cli.client import ApiArgumentParser
from cli.register_robot import register_robot

# Marks robots provisioned by this utility. Only robots with this owner are allowed to
# be represented by this utility.
ROBOT_OWNER_MARKER = "cli/add_static_enhancements"

ROBOT_DESCRIPTION = (
    "Writes static enhancements supplied by cli.add_static_enhancements. Its secret "
    "is cycled on each run and it does not poll for work of its own."
)

BATCH_SIZE = 10_000


def enhancement_input(value: str) -> EnhancementFileInput:
    """Parse an `EnhancementFileInput` passed as a json string."""
    try:
        return EnhancementFileInput.model_validate_json(value)
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def read_reference_ids(file: Path) -> set[UUID]:
    """Read reference ids from a text file, one per line."""
    return {
        UUID(line.strip()) for line in file.read_text().splitlines() if line.strip()
    }


def load_enhancements(
    enhancement_file: Path | None,
    reference_id_file: Path | None,
    enhancement: EnhancementFileInput | None,
) -> dict[UUID, Enhancement]:
    """Build the enhancement to add for each reference, keyed by reference id."""
    if enhancement_file:
        enhancements = [
            Enhancement.from_jsonl(line)
            for line in enhancement_file.read_text().splitlines()
            if line.strip()
        ]
    else:
        enhancements = [
            Enhancement(reference_id=reference_id, **enhancement.model_dump())  # type: ignore[union-attr]
            for reference_id in read_reference_ids(reference_id_file)  # type: ignore[arg-type]
        ]

    by_reference = {
        enhancement_.reference_id: enhancement_ for enhancement_ in enhancements
    }
    if len(by_reference) < len(enhancements):
        msg = "Duplicate enhancements for the same reference id are not allowed."
        raise ValueError(msg)
    return by_reference


def required_entitlements(enhancements: Iterable[Enhancement]) -> set[RobotEntitlement]:
    """Return the entitlements a robot needs in order to write these enhancements."""
    return {
        RobotEntitlement.RAW_ENHANCEMENT_WRITER
        for enhancement in enhancements
        if enhancement.content.enhancement_type == EnhancementType.RAW
    }


def resolve_robot(
    client: httpx.Client,
    robot_id: UUID | None,
    name: str | None,
    entitlements: set[RobotEntitlement],
) -> ProvisionedRobot:
    """Provision a bespoke robot, or reuse one this utility provisioned earlier."""
    if name:
        robot = register_robot(
            client,
            RobotIn(
                name=name,
                description=ROBOT_DESCRIPTION,
                owner=ROBOT_OWNER_MARKER,
                entitlements=entitlements,
            ),
        )
        print(f"Registered robot {robot.id}. Reuse it with --robot-id {robot.id}.")
        return robot

    response = client.get(f"/robots/{robot_id}/")
    response.raise_for_status()
    existing = Robot.model_validate(response.json())

    if existing.owner != ROBOT_OWNER_MARKER:
        msg = (
            f"Robot {existing.id} ({existing.name!r}, owned by {existing.owner!r}) was "
            "not provisioned by this utility. Use --create-robot instead."
        )
        raise ValueError(msg)
    if missing := entitlements - existing.entitlements:
        msg = (
            f"Robot {existing.id} is not entitled to {', '.join(sorted(missing))}, so "
            "it cannot write these enhancements."
        )
        raise ValueError(msg)

    # No secret is passed in, so take a fresh one. The owner marker makes this safe.
    print(f"Cycling the secret for robot {existing.id} ({existing.name!r}).")
    response = client.post(f"/robots/{existing.id}/secret/")
    response.raise_for_status()
    return ProvisionedRobot.model_validate(response.json())


def request_enhancements(
    client: httpx.Client,
    robot_id: UUID,
    reference_ids: set[UUID],
    source: str | None,
) -> EnhancementRequestRead:
    """Request an enhancement from the repository for each reference."""
    response = client.post(
        "/enhancement-requests/",
        json=EnhancementRequestIn(
            robot_id=robot_id,
            reference_ids=list(reference_ids),
            source=source,
        ).model_dump(mode="json"),
        timeout=120,
    )
    response.raise_for_status()
    request = EnhancementRequestRead.model_validate(response.json())
    print(
        f"Enhancement request {request.id} created for {len(reference_ids)} "
        f"references ({request.request_status})."
    )
    return request


def fulfil_enhancements(
    robot_client: RobotClient,
    robot_id: UUID,
    enhancements: dict[UUID, Enhancement],
) -> set[UUID]:
    """Act as the robot, claiming each pending batch and writing its enhancements."""
    enhanced: set[UUID] = set()
    # Batch reference and result files live on signed blob URLs, not the repository.
    with httpx.Client(timeout=120) as blob_client:
        while batch := robot_client.poll_robot_enhancement_batch(
            robot_id=robot_id, limit=BATCH_SIZE
        ):
            enhanced |= _fulfil_batch(robot_client, blob_client, batch, enhancements)
            print(f"Batch {batch.id}: {len(enhanced)}/{len(enhancements)} submitted.")
    return enhanced


def _fulfil_batch(
    robot_client: RobotClient,
    blob_client: httpx.Client,
    batch: RobotEnhancementBatch,
    enhancements: dict[UUID, Enhancement],
) -> set[UUID]:
    """Upload the static enhancements for one batch and report it complete."""
    reference_ids = _batch_reference_ids(blob_client, batch.reference_storage_url)

    if unknown := reference_ids - enhancements.keys():
        msg = (
            f"Batch {batch.id} holds {len(unknown)} reference(s) that were not "
            "requested. Abandoning the batch."
        )
        raise ValueError(msg)

    response = blob_client.put(
        str(batch.result_storage_url),
        content="\n".join(
            enhancements[reference_id].to_jsonl() for reference_id in reference_ids
        ).encode(),
        headers={
            "Content-Type": "application/jsonl",
            "x-ms-blob-type": "BlockBlob",
        },
    )
    response.raise_for_status()

    robot_client.send_robot_enhancement_batch_result(
        RobotEnhancementBatchResult(request_id=batch.id)
    )
    return reference_ids


def _batch_reference_ids(
    blob_client: httpx.Client, reference_storage_url: HttpUrl
) -> set[UUID]:
    """Read the reference ids out of a batch's reference file."""
    with blob_client.stream("GET", str(reference_storage_url)) as response:
        response.raise_for_status()
        # Only the ids are needed; validating the rest would fail the batch over data
        # this utility never looks at.
        return {
            UUID(json.loads(line)["id"])
            for line in response.iter_lines()
            if line.strip()
        }


def poll_until_complete(
    client: httpx.Client,
    request_id: UUID,
    poll_interval: float = 5,
) -> EnhancementRequestRead:
    """Poll the enhancement request until it stops progressing."""
    print(f"Polling enhancement request {request_id}...")
    while True:
        response = client.get(f"/enhancement-requests/{request_id}/")
        response.raise_for_status()
        request = EnhancementRequestRead.model_validate(response.json())
        print(f"request_status={request.request_status}")
        if request.request_status in EnhancementRequestStatus.get_terminal_statuses():
            return request
        time.sleep(poll_interval)


def add_static_enhancements(
    client: httpx.Client,
    robot: ProvisionedRobot,
    enhancements: dict[UUID, Enhancement],
    source: str | None = None,
    poll_interval: float = 5,
) -> None:
    """Request the enhancements, then write them to the repository as the robot."""
    request = request_enhancements(
        client=client,
        robot_id=robot.id,
        reference_ids=set(enhancements),
        source=source,
    )

    robot_client = RobotClient(
        base_url=HttpUrl(str(client.base_url)),
        secret_key=robot.client_secret,
        client_id=robot.id,
    )
    enhanced = fulfil_enhancements(
        robot_client=robot_client,
        robot_id=robot.id,
        enhancements=enhancements,
    )
    if missing := enhancements.keys() - enhanced:
        print(f"{len(missing)} enhancement(s) were never offered in a batch.")

    request = poll_until_complete(client, request.id, poll_interval)
    if request.request_status is EnhancementRequestStatus.PARTIAL_FAILED:
        print(
            "Enhancements already on their reference are discarded, which also "
            "reports as partial_failed."
        )
    if request.error:
        print(f"Error: {request.error}")


def argument_parser() -> ApiArgumentParser:
    """Parse the environment, the enhancements to add, and the robot to add them as."""
    parser = ApiArgumentParser(
        description=(
            "Adds a static list of enhancements to references, acting as a robot."
        )
    )

    enhancements = parser.add_mutually_exclusive_group(required=True)
    enhancements.add_argument(
        "--enhancement-file",
        type=Path,
        help="Path to a .jsonl file of `Enhancement`s, one per line.",
    )
    enhancements.add_argument(
        "--reference-id-file",
        type=Path,
        help=(
            "Path to a text file of reference ids, one per line, to apply "
            "--enhancement to."
        ),
    )
    parser.add_argument(
        "--enhancement",
        type=enhancement_input,
        help=(
            "A single `EnhancementFileInput` as json, applied to every id in "
            "--reference-id-file."
        ),
    )

    robot = parser.add_mutually_exclusive_group(required=True)
    robot.add_argument(
        "--create-robot",
        metavar="NAME",
        help="Register a bespoke robot with this name to write the enhancements.",
    )
    robot.add_argument(
        "--robot-id",
        type=UUID,
        help=(
            "ID of a robot to write the enhancements as. It must have owner "
            f"{ROBOT_OWNER_MARKER} and will have its secret cycled."
        ),
    )

    parser.add_argument(
        "--source",
        default="cli/add_static_enhancements",
        help="Source identifier for the enhancement request.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5,
        help="Seconds to wait between enhancement request status checks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without calling the repository.",
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    if args.reference_id_file and not args.enhancement:
        parser.error("--reference-id-file requires --enhancement")
    if args.enhancement_file and args.enhancement:
        parser.error("--enhancement only applies to --reference-id-file")

    try:
        enhancements = load_enhancements(
            enhancement_file=args.enhancement_file,
            reference_id_file=args.reference_id_file,
            enhancement=args.enhancement,
        )
        entitlements = required_entitlements(enhancements.values())
        print(f"{len(enhancements)} enhancements to add.")

        if args.dry_run:
            print("[DRY RUN] Nothing created.")
            sys.exit(0)

        with args.client as client:
            robot = resolve_robot(
                client=client,
                robot_id=args.robot_id,
                name=args.create_robot,
                entitlements=entitlements,
            )
            add_static_enhancements(
                client=client,
                robot=robot,
                enhancements=enhancements,
                source=args.source,
                poll_interval=args.poll_interval,
            )

    except (ValueError, httpx.HTTPError, OSError) as exc:
        print(f"Adding static enhancements failed: {exc}")
        sys.exit(1)
