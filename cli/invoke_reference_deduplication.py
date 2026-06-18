"""A utility to invoke deduplication on a csv file of reference_ids."""

# ruff: noqa: T201
from pathlib import Path

import httpx
from fastapi import status

from cli.client import ApiArgumentParser


def invoke_reference_deduplication(
    client: httpx.Client, reference_ids: list[str]
) -> int:
    """Invoke deduplication on a list of reference ids."""
    response = client.post(
        "/references/duplicate-decisions/invoke/",
        json={"reference_ids": reference_ids},
    )

    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        msg = response.json()["detail"]
        raise httpx.HTTPError(msg)

    return response.status_code


def argument_parser() -> ApiArgumentParser:
    """Parse the environment and the reference id file path."""
    parser = ApiArgumentParser()

    parser.add_argument(
        "--reference-id-file",
        type=str,
        required=True,
    )

    return parser


if __name__ == "__main__":
    parser = argument_parser()
    args = parser.parse_args()

    try:
        with Path.open(args.reference_id_file) as ref_id_file:
            reference_ids = ref_id_file.read().splitlines()

        with args.client as client:
            invoke_reference_deduplication(client=client, reference_ids=reference_ids)

        print(f"Scheduled {len(reference_ids)} deduplication tasks.")

    except (httpx.HTTPError, FileNotFoundError) as exc:
        print(f"Invoking deduplication failed: {exc}")
