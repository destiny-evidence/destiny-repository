"""Exercise distribution recovery through the API, broker and worker."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple

import httpx2
import pytest
from destiny_sdk.references import ReferenceFileInput
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.core.container import DockerContainer

from tests.e2e.conftest import host_name
from tests.e2e.utils import submit_happy_import_batch


class ImportSource(NamedTuple):
    """A JSONL source that can be interrupted after its first line."""

    url: str
    identifiers: set[str]
    requests: list[int]
    release_first: threading.Event


@pytest.fixture
def interrupted_import_source(
    generate_sdk_reference_file_inputs: Callable[[int], list[ReferenceFileInput]],
) -> Iterator[ImportSource]:
    """Hold the first response open after one line, then close it prematurely."""
    references = generate_sdk_reference_file_inputs(3)
    lines = [(reference.to_jsonl() + "\n").encode() for reference in references]
    identifiers = {
        str(identifier.identifier)
        for reference in references
        for identifier in reference.identifiers or []
    }
    requests: list[int] = []
    release_first = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            requests.append(1)
            if len(requests) == 1:
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                data = lines[0]
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                while not release_first.wait(0.25):
                    try:
                        # Keep the connection alive while the first reference imports.
                        self.wfile.write(b"1\r\n \r\n")
                    except OSError:
                        break
                return

            body = b"".join(lines)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("0.0.0.0", 0), Handler) as server:  # noqa: S104
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield ImportSource(
                f"http://{host_name}:{server.server_port}/batch.jsonl",
                identifiers,
                requests,
                release_first,
            )
        finally:
            release_first.set()
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("kill_worker", [False, True], ids=["disconnect", "sigkill"])
async def test_interrupted_distribution_imports_every_source_line(
    destiny_client_v1: httpx2.AsyncClient,
    pg_session: AsyncSession,
    worker: DockerContainer,
    interrupted_import_source: ImportSource,
    *,
    kill_worker: bool,
):
    """An interrupted file stays incomplete until every source reference arrives."""
    source = interrupted_import_source
    record_id, batch_id = await submit_happy_import_batch(destiny_client_v1, source.url)
    path = f"/imports/records/{record_id}/batches/{batch_id}/summary/"
    async with asyncio.timeout(30):
        while True:
            response = await destiny_client_v1.get(path)
            assert response.status_code == 200
            summary = response.json()
            assert summary["import_batch_status"] in ("created", "started"), summary
            if summary["results"]["completed"] == 1:
                assert summary["import_batch_status"] == "started"
                break
            await asyncio.sleep(0.2)

    if kill_worker:
        container = worker.get_wrapped_container()
        container.kill()
        container.start()
    source.release_first.set()

    async with asyncio.timeout(45):
        while True:
            response = await destiny_client_v1.get(path)
            assert response.status_code == 200
            summary = response.json()
            assert summary["import_batch_status"] in ("started", "completed"), summary
            if summary["import_batch_status"] == "completed":
                break
            await asyncio.sleep(0.2)

    assert len(source.requests) == 2
    if not kill_worker:
        assert summary["results"]["completed"] == len(source.identifiers)
    assert not summary["failure_details"]
    result = await pg_session.execute(
        text(
            "SELECT ei.identifier FROM external_identifier ei "
            "JOIN import_result ir ON ir.reference_id = ei.reference_id "
            "WHERE ir.import_batch_id = :batch_id AND ir.status = 'completed'"
        ),
        {"batch_id": batch_id},
    )
    assert set(result.scalars()) == source.identifiers
