"""A utility to check an import batch status."""

# ruff: noqa: T201
import argparse
from uuid import UUID

import destiny_sdk
import httpx
from fastapi import status
from pydantic import ValidationError

from app.core.config import Environment
from cli.auth import CLIAuth

from .config import get_settings


def check_import_batch_status(
    env: Environment, import_record_id: UUID, import_batch_id: UUID
) -> destiny_sdk.imports.ImportBatchSummary:
    """Check the status of an import batch."""
    settings = get_settings(env)

    with httpx.Client() as client:
        auth = CLIAuth(env=env)
        response = client.get(
            url=f"{str(settings.destiny_repository_url).rstrip("/")}/v1/imports/records/{import_record_id}/batches/{import_batch_id}/summary/",
            auth=auth,
        )

        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            msg = response.json()["detail"]
            raise httpx.HTTPError(msg)

        return destiny_sdk.imports.ImportBatchSummary.model_validate(response.json())


def argument_parser() -> argparse.ArgumentParser:
    """Parse the environment, import_record_id, and import_batch_id."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--import-record-id",
        type=UUID,
        required=True,
    )

    parser.add_argument(
        "--import-batch-id",
        type=UUID,
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
        import_batch_summary = check_import_batch_status(
            env=args.env,
            import_record_id=args.import_record_id,
            import_batch_id=args.import_batch_id,
        )

        print(import_batch_summary)

    except (httpx.HTTPError, ValidationError) as exc:
        print(f"Getting batch summary failed: {exc}")
