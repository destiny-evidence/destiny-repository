"""Defines tests for the example router."""

import datetime
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports import routes as imports
from app.domain.imports.models.models import (
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

# Use the database session in all tests to set up the database manager.
pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI()
    app.include_router(imports.router)
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

    response = await client.post("/imports/record/", json=import_params)

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
    response = await client.get(f"/imports/record/{valid_import.id}/")
    assert response.json()["id"] == str(valid_import.id)


async def test_get_missing_import(client: AsyncClient) -> None:
    """Test that we return a 404 when we can't find an import record."""
    response = await client.get("/imports/2526e938-b27c-44c2-887e-3bbe1c8e898a/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_create_batch_for_import(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can create a batch for an import that exists."""
    session.add(valid_import)
    await session.commit()

    batch_params = {"storage_url": "https://example.com/batch_data.json"}
    response = await client.post(
        f"/imports/record/{valid_import.id}/batch/", json=batch_params
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["import_record_id"] == str(valid_import.id)
    assert response.json()["status"] == ImportBatchStatus.CREATED
    assert response.json().items() >= batch_params.items()


async def test_get_batches(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can retrieve batches for an import."""
    session.add(valid_import)
    await session.commit()
    batch1 = SQLImportBatch(
        import_record_id=valid_import.id,
        status=ImportBatchStatus.CREATED,
        storage_url="https://some.url/file.json",
    )
    session.add(batch1)
    batch2 = SQLImportBatch(
        import_record_id=valid_import.id,
        status=ImportBatchStatus.CREATED,
        storage_url="https://files.storage/something.json",
    )
    session.add(batch2)
    await session.commit()

    response = await client.get(f"/imports/record/{valid_import.id}/batch/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2


async def test_get_import_batch_summary(
    client: AsyncClient, session: AsyncSession, valid_import: SQLImportRecord
) -> None:
    """Test that we can retrieve a summary of an import batch."""
    session.add(valid_import)
    await session.commit()
    batch = SQLImportBatch(
        import_record_id=valid_import.id,
        status=ImportBatchStatus.CREATED,
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

    response = await client.get(f"/imports/batch/{batch.id}/summary/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(batch.id)
    assert response.json()["results"] == {
        ImportResultStatus.CREATED.value: 1,
        ImportResultStatus.FAILED.value: 1,
        ImportResultStatus.PARTIALLY_FAILED.value: 1,
        ImportResultStatus.COMPLETED.value: 0,
        ImportResultStatus.CANCELLED.value: 0,
        ImportResultStatus.STARTED.value: 0,
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
        status=ImportBatchStatus.CREATED,
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

    response = await client.get(f"/imports/batch/{batch.id}/results/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 3
    response = await client.get(
        f"/imports/batch/{batch.id}/results/?result_status=failed"
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == str(result2.id)


@pytest.mark.usefixtures("stubbed_jwks_response")
async def test_auth_failure(
    client: AsyncClient,
    fake_application_id: str,
    fake_tenant_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that we reject invalid tokens."""
    with monkeypatch.context():
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("AZURE_APPLICATION_ID", fake_application_id)
        monkeypatch.setenv("AZURE_TENANT_ID", fake_tenant_id)
        imports.import_auth.reset()
        imports.settings.__init__()  # type: ignore[call-args, misc]
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
            "/imports/record/",
            json=import_params,
            headers={"Authorization": "Bearer Nonsense-token"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    imports.import_auth.reset()
    imports.settings.__init__()  # type: ignore[call-args, misc]


async def test_missing_auth(
    client: AsyncClient,
    fake_application_id: str,
    fake_tenant_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that we reject missing tokens."""
    with monkeypatch.context():
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("AZURE_APPLICATION_ID", fake_application_id)
        monkeypatch.setenv("AZURE_TENANT_ID", fake_tenant_id)
        imports.import_auth.reset()
        imports.settings.__init__()  # type: ignore[call-args, misc]
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
            "/imports/record/",
            json=import_params,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.text == '{"detail":"Authorization HTTPBearer header missing."}'
    imports.import_auth.reset()
    imports.settings.__init__()  # type: ignore[call-args, misc]
