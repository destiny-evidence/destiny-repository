"""Defines tests for the example router."""

import datetime
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid7

import pytest
import tenacity
from azure.servicebus.exceptions import ServiceBusServerBusyError
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx2 import ASGITransport, AsyncClient, HTTPStatusError
from pytest_httpx2 import HTTPXMock
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import BrokerMessage, InMemoryBroker, SendTaskError

from app.api.exception_handlers import not_found_exception_handler
from app.core.config import Environment
from app.core.exceptions import NotFoundError
from app.domain.imports import routes as imports
from app.domain.imports import tasks as import_tasks
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportDistributionStatus,
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


async def test_list_imports(
    session: AsyncSession, client: AsyncClient, valid_import: SQLImportRecord
) -> None:
    """Test that we can list all import records."""
    session.add(valid_import)
    import2 = SQLImportRecord(
        search_string="another search",
        searched_at=datetime.datetime.now(datetime.UTC),
        processor_name="test processor 2",
        processor_version="0.0.2",
        notes=None,
        source_name="EEF",
        expected_reference_count=5,
        status=ImportRecordStatus.CREATED,
    )
    session.add(import2)
    await session.commit()

    response = await client.get("/v1/imports/records/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2
    returned_ids = {r["id"] for r in response.json()}
    assert returned_ids == {str(valid_import.id), str(import2.id)}


async def test_list_imports_empty(client: AsyncClient) -> None:
    """Test that listing imports returns an empty list when none exist."""
    response = await client.get("/v1/imports/records/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


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


async def test_enqueue_batch_rejects_disallowed_domain(
    client: AsyncClient,
    session: AsyncSession,
    valid_import: SQLImportRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storage URL with a disallowed domain returns 422."""
    session.add(valid_import)
    await session.commit()

    monkeypatch.setattr(
        "app.domain.imports.routes.validate_storage_url",
        MagicMock(side_effect=ValueError("storage_url hostname is not allowed.")),
    )

    batch_params = {"storage_url": "https://disallowed.example.com/data.jsonl"}
    response = await client.post(
        f"/v1/imports/records/{valid_import.id}/batches/", json=batch_params
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "not allowed" in response.json()["detail"]


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


@pytest.fixture
async def registered_batch(
    session: AsyncSession, valid_import: SQLImportRecord
) -> SQLImportBatch:
    """Register a batch whose file each test serves."""
    session.add(valid_import)
    await session.commit()
    batch = SQLImportBatch(
        import_record_id=valid_import.id,
        storage_url="https://example.org/batch.jsonl",
    )
    session.add(batch)
    await session.commit()
    return batch


@pytest.fixture
def thirty_line_batch(
    registered_batch: SQLImportBatch,
    httpx2_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> SQLImportBatch:
    """Serve a 30-line file for the batch, and retry without waiting."""
    httpx2_mock.add_response(
        url=registered_batch.storage_url,
        text="".join(f"line {n}\n" for n in range(1, 31)),
        is_reusable=True,
    )
    monkeypatch.setattr(
        tenacity, "wait_exponential", lambda **_kwargs: tenacity.wait_none()
    )
    return registered_batch


def summary_url(batch: SQLImportBatch) -> str:
    """Build the batch summary path an importer polls."""
    return f"/v1/imports/records/{batch.import_record_id}/batches/{batch.id}/summary/"


async def complete_results(session: AsyncSession, batch: SQLImportBatch) -> None:
    """Stand in for the import_reference tasks the stubbed broker never runs."""
    await session.execute(
        update(SQLImportResult)
        .where(SQLImportResult.import_batch_id == batch.id)
        .values(status=ImportResultStatus.COMPLETED)
    )
    await session.commit()


async def test_throttled_distribution_fails_after_its_last_committed_line(
    client: AsyncClient,
    session: AsyncSession,
    thirty_line_batch: SQLImportBatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Line 27 is throttled on every attempt: started while retrying, then failed."""
    batch = thirty_line_batch
    kicks = 0
    status_while_retrying = None

    async def kick(_message: BrokerMessage) -> None:
        nonlocal kicks, status_while_retrying
        kicks += 1
        if kicks == 28:
            await complete_results(session, batch)
            response = await client.get(summary_url(batch))
            status_while_retrying = response.json()["import_batch_status"]
        if kicks > 26:
            raise ServiceBusServerBusyError

    monkeypatch.setattr(broker, "kick", kick)

    with pytest.raises(SendTaskError):
        await import_tasks.distribute_import_batch(batch.import_record_id, batch.id)

    summary = (await client.get(summary_url(batch))).json()
    assert status_while_retrying == ImportBatchStatus.STARTED
    assert summary["import_batch_status"] == ImportBatchStatus.FAILED
    assert summary["results"][ImportResultStatus.COMPLETED] == 26
    assert summary["failure_details"] == [
        "Distribution stopped after line 26 (ServiceBusServerBusyError)."
    ]


async def test_throttled_distribution_completes_when_a_retry_succeeds(
    client: AsyncClient,
    session: AsyncSession,
    thirty_line_batch: SQLImportBatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry resumes at line 27, so every line is queued exactly once."""
    batch = thirty_line_batch
    kicks = 0

    async def kick(_message: BrokerMessage) -> None:
        nonlocal kicks
        kicks += 1
        if kicks == 27:
            raise ServiceBusServerBusyError

    monkeypatch.setattr(broker, "kick", kick)

    await import_tasks.distribute_import_batch(batch.import_record_id, batch.id)
    queued = (await client.get(summary_url(batch))).json()
    await complete_results(session, batch)

    summary = (await client.get(summary_url(batch))).json()
    assert kicks == 31
    assert queued["import_batch_status"] == ImportBatchStatus.STARTED
    assert summary["import_batch_status"] == ImportBatchStatus.COMPLETED
    assert summary["results"][ImportResultStatus.COMPLETED] == 30


async def test_download_failure_fails_the_batch_with_its_status_code(
    client: AsyncClient,
    registered_batch: SQLImportBatch,
    httpx2_mock: HTTPXMock,
) -> None:
    """An expired link reads as failed, naming the status code but not the URL."""
    httpx2_mock.add_response(url=registered_batch.storage_url, status_code=403)

    with pytest.raises(HTTPStatusError):
        await import_tasks.distribute_import_batch(
            registered_batch.import_record_id, registered_batch.id
        )

    summary = (await client.get(summary_url(registered_batch))).json()
    assert summary["import_batch_status"] == ImportBatchStatus.FAILED
    assert summary["failure_details"] == [
        "Distribution stopped after line 0 (HTTP 403)."
    ]


@pytest.mark.parametrize(
    ("before", "after", "fetches"),
    [
        (None, ImportDistributionStatus.COMPLETED, 1),
        (ImportDistributionStatus.STARTED, ImportDistributionStatus.COMPLETED, 1),
        (ImportDistributionStatus.COMPLETED, ImportDistributionStatus.COMPLETED, 0),
        (ImportDistributionStatus.FAILED, ImportDistributionStatus.FAILED, 0),
    ],
)
async def test_a_delivery_distributes_only_an_unfinished_batch(  # noqa: PLR0913
    session: AsyncSession,
    registered_batch: SQLImportBatch,
    httpx2_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
    before: ImportDistributionStatus | None,
    after: ImportDistributionStatus,
    fetches: int,
) -> None:
    """A redelivery resumes a started batch; a finished one keeps its outcome."""
    registered_batch.distribution_status = before
    await session.commit()
    httpx2_mock.add_response(
        url=registered_batch.storage_url, text="line 1\n", is_optional=True
    )
    monkeypatch.setattr(broker, "kick", AsyncMock())

    await import_tasks.distribute_import_batch(
        registered_batch.import_record_id, registered_batch.id
    )

    await session.refresh(registered_batch)
    assert registered_batch.distribution_status == after
    assert len(httpx2_mock.get_requests()) == fetches


async def test_a_failure_does_not_overwrite_an_overlapping_completion(
    session: AsyncSession,
    thirty_line_batch: SQLImportBatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another delivery reaches EOF while this one is throttled out."""
    batch = thirty_line_batch
    kicks = 0

    async def kick(_message: BrokerMessage) -> None:
        nonlocal kicks
        kicks += 1
        if kicks == 27:
            batch.distribution_status = ImportDistributionStatus.COMPLETED
            await session.commit()
        if kicks >= 27:
            raise ServiceBusServerBusyError

    monkeypatch.setattr(broker, "kick", kick)

    with pytest.raises(SendTaskError):
        await import_tasks.distribute_import_batch(batch.import_record_id, batch.id)

    await session.refresh(batch)
    assert batch.distribution_status == ImportDistributionStatus.COMPLETED


async def test_reaching_eof_overrides_an_overlapping_failure(
    session: AsyncSession,
    thirty_line_batch: SQLImportBatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another delivery fails while this one queues every line."""
    batch = thirty_line_batch
    kicks = 0

    async def kick(_message: BrokerMessage) -> None:
        nonlocal kicks
        kicks += 1
        if kicks == 10:
            batch.distribution_status = ImportDistributionStatus.FAILED
            await session.commit()

    monkeypatch.setattr(broker, "kick", kick)

    await import_tasks.distribute_import_batch(batch.import_record_id, batch.id)

    await session.refresh(batch)
    assert batch.distribution_status == ImportDistributionStatus.COMPLETED


async def test_an_empty_file_completes(
    client: AsyncClient,
    registered_batch: SQLImportBatch,
    httpx2_mock: HTTPXMock,
) -> None:
    """A file with only blank lines has nothing to import, so the batch is done."""
    httpx2_mock.add_response(url=registered_batch.storage_url, text="\n \n")

    await import_tasks.distribute_import_batch(
        registered_batch.import_record_id, registered_batch.id
    )

    summary = (await client.get(summary_url(registered_batch))).json()
    assert summary["import_batch_status"] == ImportBatchStatus.COMPLETED


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
        "/v1/references/duplicate-decisions/invoke/",
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
