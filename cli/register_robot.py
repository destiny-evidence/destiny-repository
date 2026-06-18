"""A utility to register a robot in the Destiny Repository."""

# ruff: noqa: T201
import destiny_sdk
import httpx
from fastapi import status
from pydantic import ValidationError

from cli.client import ApiArgumentParser


def register_robot(
    client: httpx.Client, robot_to_register: destiny_sdk.robots.RobotIn
) -> destiny_sdk.robots.ProvisionedRobot:
    """Register a robot to destiny repository."""
    response = client.post(
        "/robots/",
        json=robot_to_register.model_dump(mode="json"),
    )

    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        msg = response.json()["detail"]
        raise httpx.HTTPError(msg)

    return destiny_sdk.robots.ProvisionedRobot.model_validate(response.json())


def argument_parser() -> ApiArgumentParser:
    """Create argument parser for robot registration."""
    parser = ApiArgumentParser(description="Register a robot to destiny respository")

    parser.add_argument(
        "-n",
        "--name",
        type=str,
        help="Name of the robot to register. Must be unique.",
        required=True,
    )

    parser.add_argument(
        "-d",
        "--description",
        type=str,
        help="A description of the robot and the enhancements it provides.",
        required=True,
    )

    parser.add_argument(
        "-o", "--owner", type=str, help="The owner of the robot", required=True
    )

    parser.add_argument(
        "--entitlement",
        type=destiny_sdk.robots.RobotEntitlement,
        choices=list(destiny_sdk.robots.RobotEntitlement),
        action="append",
        default=[],
        help=(
            "An entitlement to grant the robot. May be repeated. "
            "Requires the robot.entitlement.writer role on the caller."
        ),
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        robot_to_register = destiny_sdk.robots.RobotIn(
            name=args.name,
            description=args.description,
            owner=args.owner,
            entitlements=set(args.entitlement),
        )

        with args.client as client:
            registered_robot = register_robot(
                client=client, robot_to_register=robot_to_register
            )

        print("New Robot Registered")
        print(f"Environment: {args.env}")
        print(f"Name: {registered_robot.name}")
        print(f"Robot Id: {registered_robot.id}")
        print(f"Robot Secret: {registered_robot.client_secret}")

    except (httpx.HTTPError, ValidationError) as exc:
        print(f"Robot registration failed: {exc}")
