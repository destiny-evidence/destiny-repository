"""Tests for the reference migration utility's safeguard and export handoff."""

import json
from uuid import UUID, uuid7

import httpx
import pytest
from destiny_sdk.imports import ImportBatchStatus
from destiny_sdk.references import ExportStatus
from pytest_httpx import HTTPXMock

from app.core.config import Environment
from cli.client import get_client
from cli.migrate_references import argument_parser, migrate_references

SOURCE_URL = "https://source.example.com/v1"
DEST_URL = "https://dest.example.com/v1"
RESULT_URL = "https://source.blob.core.windows.net/exports/abc.jsonl?sig=redacted"


def _client(url: str) -> httpx.Client:
    """
    Build a client for an arbitrary base URL with no authentication.

    Must stay on a local environment. A real one attaches the SDK's OAuth
    middleware, which acquires a token on every request over its own connection
    — outside the transport ``pytest_httpx`` patches — so these tests would
    prompt an interactive login.
    """
    return get_client(Environment.LOCAL, url)


def _mock_export(httpx_mock: HTTPXMock) -> None:
    """Stub a source export that completes immediately."""
    httpx_mock.add_response(
        method="POST",
        url=f"{SOURCE_URL}/references/exports/",
        json={
            "id": str(uuid7()),
            "status": ExportStatus.COMPLETED.value,
            "export_format": "jsonl",
            "result_url": RESULT_URL,
            "n_references": 2,
            "error": None,
        },
    )


def _mock_import(httpx_mock: HTTPXMock, record_id: UUID, batch_ids: list[UUID]) -> None:
    """Stub the destination's record, batch, finalise and summary endpoints."""
    httpx_mock.add_response(
        method="POST",
        url=f"{DEST_URL}/imports/records/",
        json={
            "id": str(record_id),
            "searched_at": "2026-08-06T00:00:00Z",
            "processor_name": "cli.migrate_references",
            "processor_version": "1.0.0",
            "expected_reference_count": 2,
            "source_name": "destiny-repository-production",
            "status": "created",
        },
    )
    for batch_id in batch_ids:
        batch = {
            "id": str(batch_id),
            "storage_url": RESULT_URL,
            "import_record_id": str(record_id),
        }
        httpx_mock.add_response(
            method="POST",
            url=f"{DEST_URL}/imports/records/{record_id}/batches/",
            json=batch | {"status": ImportBatchStatus.CREATED.value},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{DEST_URL}/imports/records/{record_id}/batches/{batch_id}/",
            json=batch | {"status": ImportBatchStatus.COMPLETED.value},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"{DEST_URL}/imports/records/{record_id}/batches/{batch_id}/summary/",
            json=batch
            | {
                "import_batch_id": str(batch_id),
                "import_batch_status": ImportBatchStatus.COMPLETED.value,
                "results": {"completed": 2},
                "failure_details": None,
            },
        )
    httpx_mock.add_response(
        method="PATCH",
        url=f"{DEST_URL}/imports/records/{record_id}/finalise/",
        json={},
    )


def test_production_destination_is_not_a_valid_choice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one safeguard: argparse won't accept production as a destination."""
    with pytest.raises(SystemExit):
        argument_parser().parse_args(
            ["--reference-id-file", "ids.txt", "--dest-env", "production"]
        )

    assert "invalid choice: 'production'" in capsys.readouterr().err


def test_signed_export_url_is_handed_over_unmodified(httpx_mock: HTTPXMock) -> None:
    """The destination imports the source's file by URL; nothing is rewritten."""
    record_id, batch_id = uuid7(), uuid7()
    _mock_export(httpx_mock)
    _mock_import(httpx_mock, record_id, [batch_id])

    with _client(SOURCE_URL) as source_client, _client(DEST_URL) as dest_client:
        migrate_references(
            source_client=source_client,
            dest_client=dest_client,
            source_env=Environment.PRODUCTION,
            reference_ids=[str(uuid7()), str(uuid7())],
            notes="test",
            poll_interval=0,
        )

    batch_request = next(
        request
        for request in httpx_mock.get_requests()
        if request.method == "POST" and request.url.path.endswith("/batches/")
    )
    assert json.loads(batch_request.content)["storage_url"] == RESULT_URL


def test_ids_beyond_the_chunk_size_become_separate_batches(
    httpx_mock: HTTPXMock,
) -> None:
    """Chunking splits one import record into a batch per export."""
    record_id = uuid7()
    batch_ids = [uuid7(), uuid7()]
    for _ in batch_ids:
        _mock_export(httpx_mock)
    _mock_import(httpx_mock, record_id, batch_ids)

    with _client(SOURCE_URL) as source_client, _client(DEST_URL) as dest_client:
        migrate_references(
            source_client=source_client,
            dest_client=dest_client,
            source_env=Environment.PRODUCTION,
            reference_ids=[str(uuid7()) for _ in range(3)],
            notes="test",
            export_chunk_size=2,
            poll_interval=0,
        )

    export_sizes = [
        len(json.loads(request.content))
        for request in httpx_mock.get_requests()
        if request.method == "POST"
        and request.url.path.endswith("/references/exports/")
    ]
    assert export_sizes == [2, 1]
