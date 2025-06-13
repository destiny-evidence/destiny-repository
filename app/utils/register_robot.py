"""A utility to register a robot in azure. Utilised get_token()."""

# ruff: noqa: T201
import argparse

import destiny_sdk
import httpx
from fastapi import status
from pydantic import HttpUrl

from app.core.config import get_settings

from .get_token import get_token

settings = get_settings()


def register_robot(
    destiny_repository_url: HttpUrl,
    robot_name: str,
    robot_base_url: HttpUrl,
    robot_description: str,
    robot_owner: str,
) -> destiny_sdk.robots.ProvisionedRobot:
    """Register a robot to destiny repository."""
    robot_to_register = destiny_sdk.robots.RobotIn(
        name=robot_name,
        base_url=robot_base_url,
        description=robot_description,
        owner=robot_owner,
    )

    access_token = get_token()

    with httpx.Client() as client:
        response = client.post(
            url=str(destiny_repository_url).rstrip("/") + "/robot/",
            json=robot_to_register.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            msg = response.json()["detail"]
            raise httpx.HTTPError(msg)

        return destiny_sdk.robots.ProvisionedRobot.model_validate(response.json())


def argument_parser() -> argparse.ArgumentParser:
    """Create argument parser for robot registration."""
    parser = argparse.ArgumentParser(
        description="Register a robot to destiny respository"
    )

    parser.add_argument(
        "-n",
        "--name",
        type=str,
        help="Name of the robot to register. Must be unique.",
        required=True,
    )

    parser.add_argument(
        "-u",
        "--base-url",
        type=HttpUrl,
        help="Base url where the robot is deployed. Must be a valid HttpUrl.",
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
        "-r",
        "--repository-url",
        type=HttpUrl,
        help="The url of destiny repository.",
        required=True,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        registered_robot = register_robot(
            destiny_repository_url=args.repository_url,
            robot_name=args.name,
            robot_base_url=args.base_url,
            robot_description=args.description,
            robot_owner=args.owner,
        )

        print("New Robot Registered")
        print(f"Name: {registered_robot.name}")
        print(f"Robot Id: {registered_robot.id}")
        print(f"Robot Secret: {registered_robot.client_secret}")

    except httpx.HTTPError as exc:
        print(f"Robot registration failed: {exc}")
