"""End-to-end test for full-text enhancement materialisation during import."""

import os
import subprocess
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import httpx
from destiny_sdk.enhancements import EnhancementFileInput, FullTextEnhancement
from destiny_sdk.references import ReferenceFileInput
from destiny_sdk.visibility import Visibility

from tests.e2e.utils import poll_batch_status, submit_happy_import_batch

GetImportFileSignedUrl = Callable[
    [list[ReferenceFileInput]], AbstractAsyncContextManager[str]
]

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "full_text_sample.pdf"


def _fixture_pdf_url() -> str:
    """
    Resolve the raw.githubusercontent.com URL for the fixture PDF.

    We require a https URL to ingest full texts, and this circumvents needing to
    set up a SSL-enabled fixture.

    Works in CI via ``GITHUB_SHA`` (which always references a commit pushed to
    origin) and locally via ``git rev-parse HEAD`` (requires the branch be
    pushed - the same prerequisite as the rest of our e2e tests).
    """
    ref = (
        os.getenv("GITHUB_SHA")
        or subprocess.check_output(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            text=True,
        ).strip()
    )
    return (
        "https://raw.githubusercontent.com/destiny-evidence/destiny-repository/"
        f"{ref}/tests/e2e/fixtures/full_text_sample.pdf"
    )


async def test_happy_full_text_ingestion(
    destiny_client_v1: httpx.AsyncClient,
    get_import_file_signed_url: GetImportFileSignedUrl,
):
    """
    Full-text materialisation round-trip.

    A reference imported with a FullTextEnhancement file_url has its bytes
    copied into our blob storage, and the reference returned from the API
    exposes a signed URL that yields the PDF when followed.
    """
    expected_bytes = FIXTURE_PATH.read_bytes()
    reference_input = ReferenceFileInput(
        visibility=Visibility.PUBLIC,
        identifiers=[],
        enhancements=[
            EnhancementFileInput(
                source="e2e-test",
                visibility=Visibility.PUBLIC,
                content=FullTextEnhancement(
                    file_url=_fixture_pdf_url(),
                    byte_size=len(expected_bytes),
                    mime_type="application/pdf",
                ),
            ),
        ],
    )

    async with get_import_file_signed_url([reference_input]) as storage_url:
        import_record_id, import_batch_id = await submit_happy_import_batch(
            destiny_client_v1, storage_url
        )
        summary = await poll_batch_status(
            destiny_client_v1, import_record_id, import_batch_id
        )

    assert summary["results"]["completed"] == 1
    assert not summary["failure_details"]

    # Fetch the result to get the reference id.
    results_response = await destiny_client_v1.get(
        f"/imports/records/{import_record_id}/batches/{import_batch_id}/results/"
    )
    assert results_response.status_code == 200
    results = results_response.json()
    assert len(results) == 1
    reference_id = results[0]["reference_id"]
    assert reference_id

    # Pull the reference back via the API and verify the FT enhancement is
    # present with a signed download URL.
    reference_response = await destiny_client_v1.get(f"/references/{reference_id}/")
    assert reference_response.status_code == 200
    reference = reference_response.json()

    full_text_enhancements = [
        e
        for e in reference["enhancements"]
        if e["content"]["enhancement_type"] == "full_text"
    ]
    assert len(full_text_enhancements) == 1
    ft_content = full_text_enhancements[0]["content"]
    signed_url = ft_content["file_url"]
    assert signed_url
    # The signed URL should point at our storage, not the original source.
    assert "raw.githubusercontent.com" not in signed_url

    # Follow the URL and confirm the bytes match the fixture.
    async with httpx.AsyncClient() as fetch_client:
        download = await fetch_client.get(signed_url)
    assert download.status_code == 200
    assert download.content == expected_bytes
