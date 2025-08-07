"""A utility to register a robot in azure. Utilised get_token()."""

# ruff: noqa: T201
import argparse

import destiny_sdk
import httpx
from fastapi import status
from pydantic import HttpUrl, ValidationError

from app.core.config import Environment
from cli.auth import CLIAuth

from .config import get_settings


def register_robot(
    env: Environment, robot_to_register: destiny_sdk.robots.RobotIn
) -> destiny_sdk.robots.ProvisionedRobot:
    """Register a robot to destiny repository."""
    settings = get_settings(env)

    with httpx.Client() as client:
        auth = CLIAuth(env=env)
        response = client.post(
            url=str(settings.destiny_repository_url).rstrip("/") + "/v1/robots/",
            json=robot_to_register.model_dump(mode="json"),
            auth=auth,
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
        "-e",
        "--env",
        type=Environment,
        default=Environment.LOCAL,
        help="The environment to create the robot in",
        required=True,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        robot_to_register = destiny_sdk.robots.RobotIn(
            name=args.name,
            base_url=args.base_url,
            description=args.description,
            owner=args.owner,
        )

        registered_robot = register_robot(
            env=args.env, robot_to_register=robot_to_register
        )

        print("New Robot Registered")
        print(f"Environment: {args.env}")
        print(f"Name: {registered_robot.name}")
        print(f"Robot Id: {registered_robot.id}")
        print(f"Robot Secret: {registered_robot.client_secret}")

    except (httpx.HTTPError, ValidationError) as exc:
        print(f"Robot registration failed: {exc}")
