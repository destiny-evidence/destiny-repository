"""Test import records exercising the full app."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.main import app

valid_import_record_params = {
    "search_string": "climate AND health",
    "searched_at": "2025-02-02T13:29:30Z",
    "processor_name": "Test Importer",
    "processor_version": "0.0.1",
    "notes": "This is not a real import, it is only a test run.",
    "expected_reference_count": 100,
    "source_name": "OpenAlex",
}


# Use the session for all tests so the database manager is initialized.
pytestmark = pytest.mark.usefixtures("session")


@pytest.fixture
async def client(app: FastAPI = app) -> AsyncIterator[AsyncClient]:
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
        headers={"Authorization": "Bearer foo"},
    ) as client:
        yield client


async def test_create_and_read_import_record(client: AsyncClient) -> None:
    """Test creating an import record then reading it."""
    create_response = await client.post(
        "/imports/record/", json=valid_import_record_params
    )
    assert create_response.status_code == status.HTTP_201_CREATED

    import_id = create_response.json()["id"]
    read_response = await client.get(f"/imports/record/{import_id}/")
    assert read_response.json().items() >= valid_import_record_params.items()
