"""End-to-end test for full-text enhancement storage during import."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from destiny_sdk.enhancements import EnhancementFileInput, FullTextEnhancement
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import ReferenceFileInput
from destiny_sdk.visibility import Visibility

from tests.e2e.conftest import host_name
from tests.e2e.utils import poll_batch_status, submit_happy_import_batch

GetImportFileSignedUrl = Callable[
    [list[ReferenceFileInput]], AbstractAsyncContextManager[str]
]

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "full_text_sample.pdf"


@pytest.fixture
def serve_fixture_pdf() -> Callable[[], AbstractAsyncContextManager[str]]:
    """
    Serve the fixture PDF over http on a local aiohttp server.

    The same pattern as ``get_import_file_signed_url`` for the importer JSONL.
    Yields the URL the app container can reach via ``host_name``.
    """

    @asynccontextmanager
    async def _serve() -> AsyncIterator[str]:
        name = FIXTURE_PATH.name

        async def handle(_request: web.Request) -> web.FileResponse:
            return web.FileResponse(FIXTURE_PATH)

        app = web.Application()
        app.router.add_get(f"/{name}", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 0)  # noqa: S104
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr, attr-defined]  # noqa: SLF001
        try:
            yield f"http://{host_name}:{port}/{name}"
        finally:
            await runner.cleanup()

    return _serve


async def test_happy_full_text_ingestion(
    destiny_client_v1: httpx.AsyncClient,
    get_import_file_signed_url: GetImportFileSignedUrl,
    serve_fixture_pdf: Callable[[], AbstractAsyncContextManager[str]],
    minio_proxy_client: httpx.AsyncClient,
):
    """
    Full-text storage round-trip.

    A reference imported with a FullTextEnhancement file_url has its bytes
    copied into our blob storage, and the reference returned from the API
    exposes a URL that yields the PDF when followed.
    """
    expected_bytes = FIXTURE_PATH.read_bytes()

    async with serve_fixture_pdf() as fixture_url:
        reference_input = ReferenceFileInput(
            visibility=Visibility.PUBLIC,
            identifiers=[DOIIdentifier(identifier="10.1000/e2e-full-text-test")],
            enhancements=[
                EnhancementFileInput(
                    source="e2e-test",
                    visibility=Visibility.PUBLIC,
                    content=FullTextEnhancement(
                        file_url=fixture_url,
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

        # Always fetch results so we have failure_details on hand for the assertion.
        results_response = await destiny_client_v1.get(
            f"/imports/records/{import_record_id}/batches/{import_batch_id}/results/"
        )
        assert results_response.status_code == 200
        results = results_response.json()

        diagnostic = {"summary": summary, "results": results}
        assert summary["results"]["completed"] == 1, diagnostic
        assert not summary["failure_details"], diagnostic

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
        assert signed_url != fixture_url

        download = await minio_proxy_client.get("", params={"url": signed_url})
        assert download.status_code == 200
        assert download.content == expected_bytes
