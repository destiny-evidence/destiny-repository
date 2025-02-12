"""Defines tests for the example router."""

import datetime
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_record import ImportRecord, ImportStatus
from app.routers import imports

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
        transport=ASGITransport(app=app), base_url="http://test"
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
        "expected_record_count": 100,
        "source_name": "OpenAlex",
    }

    response = await client.post("/imports/", json=import_params)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json().items() >= {**import_params}.items()
    assert response.json()["status"] == ImportStatus.created
    data = await session.get(ImportRecord, response.json()["id"])
    assert data is not None


valid_import = ImportRecord(
    search_string="search AND string",
    searched_at=datetime.datetime.now(datetime.UTC),
    processor_name="test processor",
    processor_version="0.0.1",
    notes="No notes.",
    source_name="The internet",
    expected_record_count=12,
)


async def test_get_import(session: AsyncSession, client: AsyncClient) -> None:
    """Test that we can read an import from the database."""
    session.add(valid_import)
    await session.commit()
    response = await client.get(f"/imports/{valid_import.id}")
    assert response.json()["id"] == str(valid_import.id)


async def test_get_missing_import(client: AsyncClient) -> None:
    """Test that we return a 404 when we can't find an import record."""
    response = await client.get("/imports/2526e938-b27c-44c2-887e-3bbe1c8e898a")
    assert response.status_code == status.HTTP_404_NOT_FOUND
