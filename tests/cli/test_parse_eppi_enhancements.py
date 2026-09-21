"""Tests for the EPPI enhancement parser's verification and output."""

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid7

import httpx
import pytest
from destiny_sdk.enhancements import Enhancement, EnhancementType
from destiny_sdk.parsers.exceptions import ReferenceIdNotFoundError
from pytest_httpx import HTTPXMock

from app.core.config import Environment
from cli.client import get_client
from cli.parse_eppi_enhancements import (
    argument_parser,
    parse_eppi_enhancements,
    verify_references,
)

REFERENCE_ID = UUID("019f880e-2c39-7138-a387-221808f02d98")
REFERENCE_URL = f"https://data.evidence-repository.org/esea/references/{REFERENCE_ID}"
SOURCE = "eef-eppi-review"


def _export(tmp_path: Path, *references: dict) -> Path:
    """Write an EPPI export holding the given references."""
    path = tmp_path / "eppi_export.json"
    path.write_bytes(
        json.dumps(
            {"CodeSets": [{"SetId": 96392}], "References": list(references)},
            ensure_ascii=False,
        ).encode("utf-8")
    )
    return path


def _args(export: Path, output: Path, *extra: str) -> argparse.Namespace:
    """Build the arguments for a run against the given export."""
    return argument_parser().parse_args(
        [
            "--input",
            str(export),
            "--output",
            str(output),
            "--source",
            SOURCE,
            "--description",
            "EEF additional coding request",
            "--source-export-date",
            "2026-09-16",
            *extra,
        ]
    )


def test_enhancement_is_written_for_each_verified_reference(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """A reference the repository knows is written out as a raw enhancement."""
    export = _export(
        tmp_path,
        {
            "ItemId": 116012899,
            "URL": REFERENCE_URL,
            "Abstract": "Excluded from the raw enhancement.",
            "Codes": [{"AttributeId": 5215229}],
        },
    )
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        json={"id": str(REFERENCE_ID), "visibility": "public"},
    )

    parse_eppi_enhancements(_args(export, output))

    enhancement = Enhancement.from_jsonl(output.read_text().splitlines()[0])
    assert enhancement.reference_id == REFERENCE_ID
    assert enhancement.source == SOURCE
    assert enhancement.content.enhancement_type == EnhancementType.RAW
    assert enhancement.content.metadata == {"codeset_ids": [96392]}
    assert not enhancement.content.data.get("Abstract")


def test_reference_not_in_the_repository_writes_nothing(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Enhancements are only written once every reference is known to exist."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL})
    output = tmp_path / "enhancements.jsonl"
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{REFERENCE_ID}/",
        status_code=404,
    )

    with pytest.raises(ValueError, match="not in the repository"):
        parse_eppi_enhancements(_args(export, output))

    assert not output.exists()


def test_reference_without_an_id_is_never_verified(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """An export we can't attach fails before any reference is looked up."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": "https://eppi.example/1"})
    output = tmp_path / "enhancements.jsonl"

    with pytest.raises(ReferenceIdNotFoundError, match="ItemId 116012899"):
        parse_eppi_enhancements(_args(export, output))

    assert not httpx_mock.get_requests()
    assert not output.exists()


def test_skip_verification_asks_the_repository_nothing(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """A disconnected run writes the enhancements without checking them."""
    export = _export(tmp_path, {"ItemId": 116012899, "URL": REFERENCE_URL})
    output = tmp_path / "enhancements.jsonl"

    parse_eppi_enhancements(_args(export, output, "--skip-verification"))

    assert not httpx_mock.get_requests()
    assert len(output.read_text().splitlines()) == 1


def test_unauthorized_verification_is_not_reported_as_a_missing_reference(
    httpx_mock: HTTPXMock,
) -> None:
    """A rejected request says so, rather than claiming the reference is absent."""
    reference_id = uuid7()
    httpx_mock.add_response(
        method="GET",
        url=f"http://127.0.0.1:8000/v1/references/{reference_id}/",
        status_code=401,
    )

    with (
        get_client(Environment.LOCAL) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        verify_references(client, {reference_id})
