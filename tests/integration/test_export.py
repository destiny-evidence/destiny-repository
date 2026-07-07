"""Integration tests for the reference export endpoints."""

from collections.abc import AsyncGenerator
from uuid import uuid7

import destiny_sdk
import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import (
    es_exception_handler,
    not_found_exception_handler,
    parse_error_exception_handler,
)
from app.core.exceptions import ESQueryError, NotFoundError, ParseError
from app.domain.references import routes as references
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.repository import ReferenceESRepository
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
)
from app.persistence.blob.repository import BlobRepository
from app.persistence.blob.stream import FileStream
from app.tasks import broker
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    ReferenceFactory,
    to_indexable,
)

pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application instance for testing."""
    app = FastAPI(
        exception_handlers={
            ESQueryError: es_exception_handler,
            ParseError: parse_error_exception_handler,
            NotFoundError: not_found_exception_handler,
        }
    )
    app.include_router(references.reference_router, prefix="/v1")
    return app


@pytest.fixture
async def client(
    app: FastAPI,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client for the FastAPI application."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def es_reference_repository(
    es_client: AsyncElasticsearch,
) -> ReferenceESRepository:
    """Fixture to create an Elasticsearch reference repository."""
    return ReferenceESRepository(client=es_client)


async def test_search_export_end_to_end(
    session: AsyncSession,
    client: AsyncClient,
    es_reference_repository: ReferenceESRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    POST → task → GET: assert the produced JSONL bytes round-trip to references.

    Patches only ``BlobRepository.upload_file_to_blob_storage`` (to capture the
    bytes the FileStream emits) and ``BlobRepository.get_signed_url`` (so the
    GET poll returns a deterministic URL). Everything else — search routing,
    job persistence, broker dispatch, ES query, SQL hydration, JSONL
    conversion — runs against real Postgres and Elasticsearch.
    """
    matching_one = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Climate review one",
                )
            )
        ]
    )
    matching_two = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Climate review two",
                )
            )
        ]
    )
    unmatched = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Mosquito surveillance",
                )
            )
        ]
    )

    session.add_all(
        [SQLReference.from_domain(r) for r in (matching_one, matching_two, unmatched)]
    )
    await session.commit()

    for reference in (matching_one, matching_two, unmatched):
        await es_reference_repository.add(to_indexable(reference))
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    captured: bytearray = bytearray()

    async def fake_upload(
        self: BlobRepository,  # noqa: ARG001
        content: FileStream,
        path: str,
        filename: str,
        **_: object,
    ) -> BlobStorageFile:
        async for chunk in content.stream():
            captured.extend(chunk)
        return BlobStorageFile(
            location="minio",
            container="destiny-repository",
            path=path,
            filename=filename,
        )

    async def fake_signed_url(
        self: BlobRepository,  # noqa: ARG001
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> HttpUrl:
        return HttpUrl(f"http://signed/{file.filename}/{interaction_type}")

    monkeypatch.setattr(BlobRepository, "upload_file_to_blob_storage", fake_upload)
    monkeypatch.setattr(BlobRepository, "get_signed_url", fake_signed_url)

    post_response = await client.post(
        "/v1/references/search/exports/", params={"q": "Climate"}
    )
    assert post_response.status_code == status.HTTP_202_ACCEPTED
    export_id = post_response.json()["id"]

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

    get_response = await client.get(f"/v1/references/search/exports/{export_id}/")
    assert get_response.status_code == status.HTTP_200_OK
    body = get_response.json()
    assert body["status"] == "completed"
    assert body["n_references"] == 2
    assert body["truncated"] is False
    assert body["result_url"] is not None
    assert body["error"] is None

    lines = [line for line in captured.decode("utf-8").splitlines() if line]
    assert len(lines) == 2
    parsed_ids = {
        destiny_sdk.references.Reference.from_jsonl(line).id for line in lines
    }
    assert parsed_ids == {matching_one.id, matching_two.id}


async def test_search_export_ris_end_to_end(
    session: AsyncSession,
    client: AsyncClient,
    es_reference_repository: ReferenceESRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST ?export_format=ris → task → GET produces an RIS file of the matches."""
    matching_one = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Climate review one",
                )
            )
        ]
    )
    matching_two = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Climate review two",
                )
            )
        ]
    )
    unmatched = ReferenceFactory.build(
        enhancements=[
            EnhancementFactory.build(
                content=BibliographicMetadataEnhancementFactory.build(
                    title="Mosquito surveillance",
                )
            )
        ]
    )

    session.add_all(
        [SQLReference.from_domain(r) for r in (matching_one, matching_two, unmatched)]
    )
    await session.commit()

    for reference in (matching_one, matching_two, unmatched):
        await es_reference_repository.add(to_indexable(reference))
    await es_reference_repository._client.indices.refresh(  # noqa: SLF001
        index=es_reference_repository._persistence_cls.Index.name,  # noqa: SLF001
    )

    captured: bytearray = bytearray()

    async def fake_upload(
        self: BlobRepository,  # noqa: ARG001
        content: FileStream,
        path: str,
        filename: str,
        **_: object,
    ) -> BlobStorageFile:
        async for chunk in content.stream():
            captured.extend(chunk)
        return BlobStorageFile(
            location="minio",
            container="destiny-repository",
            path=path,
            filename=filename,
        )

    async def fake_signed_url(
        self: BlobRepository,  # noqa: ARG001
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> HttpUrl:
        return HttpUrl(f"http://signed/{file.filename}/{interaction_type}")

    monkeypatch.setattr(BlobRepository, "upload_file_to_blob_storage", fake_upload)
    monkeypatch.setattr(BlobRepository, "get_signed_url", fake_signed_url)

    post_response = await client.post(
        "/v1/references/search/exports/",
        params={"q": "Climate", "export_format": "ris"},
    )
    assert post_response.status_code == status.HTTP_202_ACCEPTED
    assert post_response.json()["export_format"] == "ris"
    export_id = post_response.json()["id"]

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

    get_response = await client.get(f"/v1/references/search/exports/{export_id}/")
    assert get_response.status_code == status.HTTP_200_OK
    body = get_response.json()
    assert body["status"] == "completed"
    assert body["export_format"] == "ris"
    assert body["n_references"] == 2
    assert ".ris" in body["result_url"]

    text = captured.decode("utf-8")
    assert text.count("TY  - ") == 2
    assert text.count("ER  - ") == 2
    assert "TI  - Climate review one" in text
    assert "TI  - Climate review two" in text


def _patch_blob_storage(monkeypatch: pytest.MonkeyPatch) -> bytearray:
    """Capture bytes streamed to blob storage; return the buffer they land in."""
    captured = bytearray()

    async def fake_upload(
        self: BlobRepository,  # noqa: ARG001
        content: FileStream,
        path: str,
        filename: str,
        **_: object,
    ) -> BlobStorageFile:
        async for chunk in content.stream():
            captured.extend(chunk)
        return BlobStorageFile(
            location="minio",
            container="destiny-repository",
            path=path,
            filename=filename,
        )

    async def fake_signed_url(
        self: BlobRepository,  # noqa: ARG001
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> HttpUrl:
        return HttpUrl(f"http://signed/{file.filename}/{interaction_type}")

    monkeypatch.setattr(BlobRepository, "upload_file_to_blob_storage", fake_upload)
    monkeypatch.setattr(BlobRepository, "get_signed_url", fake_signed_url)
    return captured


async def test_reference_export_end_to_end(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    POST ids → task → GET: the produced JSONL contains exactly the chosen refs.

    No Elasticsearch indexing: a reference export fetches by primary key.
    """
    selected_one = ReferenceFactory.build()
    selected_two = ReferenceFactory.build()
    unselected = ReferenceFactory.build()

    session.add_all(
        [SQLReference.from_domain(r) for r in (selected_one, selected_two, unselected)]
    )
    await session.commit()

    captured = _patch_blob_storage(monkeypatch)

    post_response = await client.post(
        "/v1/references/exports/",
        json=[str(selected_one.id), str(selected_two.id)],
    )
    assert post_response.status_code == status.HTTP_202_ACCEPTED
    body = post_response.json()
    export_id = body["id"]
    # Reference exports never truncate.
    assert "truncated" not in body

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()

    get_response = await client.get(f"/v1/references/exports/{export_id}/")
    assert get_response.status_code == status.HTTP_200_OK
    body = get_response.json()
    assert body["status"] == "completed"
    assert body["n_references"] == 2
    assert body["result_url"] is not None
    assert body["error"] is None

    lines = [line for line in captured.decode("utf-8").splitlines() if line]
    assert len(lines) == 2
    parsed_ids = {
        destiny_sdk.references.Reference.from_jsonl(line).id for line in lines
    }
    assert parsed_ids == {selected_one.id, selected_two.id}


async def test_reference_export_rejects_empty_list(client: AsyncClient) -> None:
    """An empty id list is rejected by request validation."""
    response = await client.post(
        "/v1/references/exports/",
        json=[],
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_reference_export_rejects_unknown_id(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """An id that doesn't resolve is rejected up front with a structured 422."""
    existing = ReferenceFactory.build()
    session.add(SQLReference.from_domain(existing))
    await session.commit()
    missing_id = uuid7()

    response = await client.post(
        "/v1/references/exports/",
        json=[str(existing.id), str(missing_id)],
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert str(missing_id) in str(response.json()["detail"])
