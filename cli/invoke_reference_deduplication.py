"""A utility to invoke deduplication on a csv file of reference_ids."""

# ruff: noqa: T201
import argparse
from pathlib import Path

import httpx
from fastapi import status

from app.core.config import Environment
from cli.auth import CLIAuth

from .config import get_settings


def invoke_reference_deduplication(env: Environment, reference_ids: list[str]) -> int:
    """Invoke deduplication on a list of reference ids."""
    settings = get_settings(env)

    with httpx.Client() as client:
        auth = CLIAuth(env=env)
        base_url = str(settings.destiny_repository_url).rstrip("/")
        response = client.post(
            url=f"{base_url}/v1/references/duplicate-decisions/invoke/",
            json={"reference_ids": reference_ids},
            auth=auth,
        )

        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            msg = response.json()["detail"]
            raise httpx.HTTPError(msg)

        return response.status_code


def argument_parser() -> argparse.ArgumentParser:
    """Parse the environment and the reference id file path."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--reference-id-file",
        type=str,
        required=True,
    )

    parser.add_argument(
        "-e",
        "--env",
        type=Environment,
        default=Environment.LOCAL,
        required=True,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with Path.open(args.reference_id_file) as ref_id_file:
            reference_ids = ref_id_file.read().splitlines()

        invoke_status = invoke_reference_deduplication(
            reference_ids=reference_ids, env=args.env
        )

        print(f"Scheduled {len(reference_ids)} deduplication tasks.")

    except (httpx.HTTPError, FileNotFoundError) as exc:
        print(f"Invoking deduplication failed: {exc}")
