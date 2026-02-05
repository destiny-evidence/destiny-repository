"""Defines tests for the example router."""

import datetime
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock
from uuid import UUID, uuid7

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import not_found_exception_handler
from app.core.config import Environment
from app.core.exceptions import NotFoundError
from app.domain.imports import routes as imports
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRecordStatus,
    ImportResultStatus,
)
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
)
from app.domain.imports.models.sql import (
    ImportResult as SQLImportResult,
)
from app.domain.imports.service import ImportService
from app.domain.references import routes as references
from app.domain.references.models.sql import ReferenceDuplicateDecision
from app.tasks import broker

# Use the database session in all tests to set up the database manager.
pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI(
        exception_handlers={
            NotFoundError: not_found_exception_handler,
        }
    )
    app.include_router(imports.router, prefix="/v1")
    app.include_router(references.reference_router, prefix="/v1")
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """
    Create a test client for the FastAPI application.

    Args:
        app (FastAPI): FastAPI application instance.

    Returns:
        TestClient: Test client for the FastAPI application.

    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_create_import(session: AsyncSession, client: AsyncClient) -> None:
    """
    Test the happy path of creating an import.

    Arg:
      client (TestClient): Test Client for the FastAPI App
    """
    import_params = {
        "search_string": "climate AND health",
        "searched_at": "2025-02-02T13:29:30Z",
        "processor_name": "Test Importer",
        "processor_version": "0.0.1",
        "notes": "This is not a real import, it is only a test run.",
        "expected_reference_count": 100,
        "source_name": "OpenAlex",
    }

    response = await client.post("/v1/imports/records/", json=import_params)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json().items() >= {**import_params}.items()
    assert response.json()["status"] == ImportRecordStatus.CREATED
    data = await session.get(SQLImportRecord, response.json()["id"])
    assert data is not None


@pytest.fixture
def valid_import() -> SQLImportRecord:
    """Create a new valid import for testing."""
    return SQLImportRecord(
        search_string="search AND string",
        searched_at=datetime.datetime.now(datetime.UTC),
        processor_name="test processor",
        processor_version="0.0.1",
        notes="No notes.",
        source_name="The internet",
        expected_reference_count=12,
        status=ImportRecordStatus.CREATED,
    )


async def test_get_import(
    session: AsyncSession, client: AsyncClient, valid_import: SQLImportRecord
) -> None:
    """Test that we can read an import from the database."""
    session.add(valid_import)
    await session.commit()
    response = await client.get(f"/v1/imports/records/{valid_import.id}/")
    assert response.json()["id"] == str(valid_import.id)


async def test_get_missing_import(client: AsyncClient) -> None:
    """Test that we return a 404 when we can't find an import record."""
    response = await client.get(
        "/v1/imports/records/2526e938-b27c-44c2-887e-3bbe1c8e898a/"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert (
        response.json()["detail"]
        == "ImportRecord with id 2526e938-b27c-44c2-887e-3bbe1c8e898a does not exist."
    )


async def test_create_batch_for_import(
    client: AsyncClient,
    session: AsyncSession,
    es_client: AsyncElasticsearch,  # noqa: ARG001
    valid_import: SQLImportRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test that we can create a batch for an import that exists.

    Also verifies the call arguments of the procedure:
    - The importing of the batch
    - The indexing in elasticsearch
    - The default enhancement generation
    """
    session.add(valid_import)
    await session.commit()

    # Mock the ImportService.distribute_import_batch call
    mock_process = AsyncMock(return_value=None)
    monkeypatch.setattr(ImportService, "distribute_import_batch", mock_process)

    batch_params = {"storage_url": "https://example.com/batch_data.json"}
    response = await client.post(
        f"/v1/imports/records/{valid_import.id}/batches/", json=batch_params
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["import_record_id"] == str(valid_import.id)
    assert response.json()["status"] == ImportBatchStatus.CREATED
    assert response.json().items() >= batch_params.items()

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()  # Wait for all async tasks to complete
    mock_process.assert_awaited_once()

    assert mock_process.call_args[0][0] == ImportBatch(
        id=UUID(response.json()["id"]),
        import_record_id=valid_import.id,
        status=ImportBatchStatus.CREATED,
        storage_url="https://example.com/batch_data.json",
    )


async def test_get_batches(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can retrieve batches for an import."""
    session.add(valid_import)
    await session.commit()
    batch1 = SQLImportBatch(
        import_record_id=valid_import.id,
        storage_url="https://some.url/file.json",
    )
    session.add(batch1)
    batch2 = SQLImportBatch(
        import_record_id=valid_import.id,
        storage_url="https://files.storage/something.json",
    )
    session.add(batch2)
    await session.commit()

    response = await client.get(f"/v1/imports/records/{valid_import.id}/batches/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2
    assert response.json()[0]["status"] == "created"


async def test_get_import_batch_summary(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can retrieve a summary of an import batch."""
    session.add(valid_import)
    await session.commit()
    batch = SQLImportBatch(
        import_record_id=valid_import.id,
        storage_url="https://some.url/file.json",
    )
    session.add(batch)
    await session.commit()
    result1 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.CREATED,
    )
    session.add(result1)
    result2 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.FAILED,
        failure_details="Some failure details.",
    )
    session.add(result2)
    result3 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.PARTIALLY_FAILED,
        failure_details="Some other failure details.",
    )
    session.add(result3)
    await session.commit()

    response = await client.get(
        f"/v1/imports/records/{valid_import.id}/batches/{batch.id}/summary/"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(batch.id)
    assert response.json()["results"] == {
        ImportResultStatus.CREATED.value: 1,
        ImportResultStatus.FAILED.value: 1,
        ImportResultStatus.PARTIALLY_FAILED.value: 1,
        ImportResultStatus.COMPLETED.value: 0,
        ImportResultStatus.STARTED.value: 0,
        ImportResultStatus.RETRYING.value: 0,
    }
    assert response.json()["failure_details"] == [
        "Some failure details.",
        "Some other failure details.",
    ]


async def test_get_import_results(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can retrieve a summary of an import batch."""
    session.add(valid_import)
    await session.commit()
    batch = SQLImportBatch(
        import_record_id=valid_import.id,
        storage_url="https://some.url/file.json",
    )
    session.add(batch)
    await session.commit()
    result1 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.CREATED,
    )
    session.add(result1)
    result2 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.FAILED,
        failure_details="Some failure details.",
    )
    session.add(result2)
    result3 = SQLImportResult(
        import_batch_id=batch.id,
        status=ImportResultStatus.PARTIALLY_FAILED,
        failure_details="Some other failure details.",
    )
    session.add(result3)
    await session.commit()

    response = await client.get(
        f"/v1/imports/records/{valid_import.id}/batches/{batch.id}/results/"
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 3
    response = await client.get(
        f"/v1/imports/records/{valid_import.id}/batches/{batch.id}/results/?result_status=failed"
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == str(result2.id)


@pytest.mark.usefixtures("stubbed_jwks_response")
async def test_auth_failure(client: AsyncClient, fake_application_id: str):
    """Test that we reject invalid tokens."""
    imports.settings.env = Environment.PRODUCTION
    imports.settings.azure_application_id = fake_application_id
    imports.import_auth.reset()

    import_params = {
        "search_string": "climate AND health",
        "searched_at": "2025-02-02T13:29:30Z",
        "processor_name": "Test Importer",
        "processor_version": "0.0.1",
        "notes": "This is not a real import, it is only a test run.",
        "expected_reference_count": 100,
        "source_name": "OpenAlex",
    }

    response = await client.post(
        "/v1/imports/records/",
        json=import_params,
        headers={"Authorization": "Bearer Nonsense-token"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    imports.settings.__init__()  # type: ignore[call-args, misc]
    imports.import_auth.reset()


async def test_missing_auth(
    client: AsyncClient,
    fake_application_id: str,
):
    """Test that we reject missing tokens."""
    imports.settings.env = Environment.PRODUCTION
    imports.settings.azure_application_id = fake_application_id
    imports.import_auth.reset()

    import_params = {
        "search_string": "climate AND health",
        "searched_at": "2025-02-02T13:29:30Z",
        "processor_name": "Test Importer",
        "processor_version": "0.0.1",
        "notes": "This is not a real import, it is only a test run.",
        "expected_reference_count": 100,
        "source_name": "OpenAlex",
    }

    response = await client.post(
        "/v1/imports/records/",
        json=import_params,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.text == '{"detail":"Authorization HTTPBearer header missing."}'

    imports.import_auth.reset()
    imports.settings.__init__()  # type: ignore[call-args, misc]


async def test_missing_import_record(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we return a 404 when we try to access batches for a missing record."""
    session.add(valid_import)
    await session.commit()

    response = await client.get(f"/v1/imports/records/{(_id:=uuid7())}/batches/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == f"ImportRecord with id {_id} does not exist."


async def test_deduplicate_references(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """
    Test that we can deduplicate references for an import record.

    NB this test takes advantage of the fact that duplicate_decision doesn't
    FK to Reference (see app.domain.references.models.sql.ReferenceDuplicateDecision
    for more). If that changes, this test will need seeding.
    """
    mock_queue = AsyncMock()
    monkeypatch.setattr(
        "app.domain.references.service.queue_task_with_trace", mock_queue
    )

    ref_ids = {uuid7(), uuid7(), uuid7()}
    response = await client.post(
        "/v1/references/duplicate-decisions/",
        json={"reference_ids": [str(r) for r in ref_ids]},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED

    # Assert queue_task_with_trace was called 3 times with correct IDs
    assert mock_queue.call_count == 3
    called_ids = {
        call.kwargs["reference_duplicate_decision_id"]
        for call in mock_queue.call_args_list
    }

    data = await session.execute(select(ReferenceDuplicateDecision))
    results = data.scalars().all()
    assert len(results) == 3
    assert {r.reference_id for r in results} == ref_ids
    assert {r.duplicate_determination for r in results} == {"pending"}
    assert {r.id for r in results} == called_ids
