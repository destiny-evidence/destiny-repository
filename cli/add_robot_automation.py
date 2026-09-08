"""A utility to add a robot automation to the Destiny Repository."""

# ruff: noqa: T201
import json
from pathlib import Path

import destiny_sdk
import httpx
from fastapi import status
from pydantic import ValidationError

from cli.client import ApiArgumentParser


def add_robot_automation(
    client: httpx.Client, automation: destiny_sdk.robots.RobotAutomationIn
) -> destiny_sdk.robots.RobotAutomation:
    """Add a robot automation to destiny repository."""
    response = client.post(
        "/enhancement-requests/automations/",
        json=automation.model_dump(mode="json"),
    )

    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        msg = response.json().get("detail", response.text)
        raise httpx.HTTPError(msg)

    return destiny_sdk.robots.RobotAutomation.model_validate(response.json())


def argument_parser() -> ApiArgumentParser:
    """Create argument parser for adding a robot automation."""
    parser = ApiArgumentParser(
        description="Add a robot automation to destiny repository"
    )

    parser.add_argument(
        "-r",
        "--robot-id",
        type=str,
        help="The ID of the robot to request enhancements from on a match.",
        required=True,
    )

    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument(
        "-q",
        "--query",
        type=str,
        help="The percolator query, as a JSON string.",
    )
    query.add_argument(
        "-f",
        "--query-file",
        type=Path,
        help="Path to a file containing the percolator query as JSON.",
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        raw_query = args.query if args.query else args.query_file.read_text()
        automation_to_add = destiny_sdk.robots.RobotAutomationIn(
            robot_id=args.robot_id,
            query=json.loads(raw_query),
        )

        with args.client as client:
            added_automation = add_robot_automation(
                client=client, automation=automation_to_add
            )

        print("New Robot Automation Added")
        print(f"Environment: {args.env}")
        print(f"Automation Id: {added_automation.id}")
        print(f"Robot Id: {added_automation.robot_id}")
        print(f"Query: {json.dumps(added_automation.query)}")

    except (httpx.HTTPError, ValidationError, json.JSONDecodeError, OSError) as exc:
        print(f"Adding robot automation failed: {exc}")
