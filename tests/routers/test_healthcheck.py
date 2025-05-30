"""Defines tests for the healthcheck router."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.persistence.sql.session import get_session
from app.utils import healthcheck


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI(title="Test Healthcheck")
    app.include_router(healthcheck.router)
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


async def test_healthcheck_success(app: FastAPI, client: AsyncClient) -> None:
    """Test the happy path of the healthcheck."""
    mock_session = AsyncMock()
    mock_session.execute.return_value = None  # Simulating successful DB query

    async def mock_get_session() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    app.dependency_overrides[get_session] = mock_get_session
    response = await client.get("/healthcheck/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


async def test_healthcheck_failure(app: FastAPI, client: AsyncClient) -> None:
    """Test the DB connection failure path of the healthcheck."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = Exception("Database failure")

    async def mock_get_session() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    app.dependency_overrides[get_session] = mock_get_session
    response = await client.get(
        "/healthcheck/",
        params={"database": True, "worker": False, "azure_blob_storage": False},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {"detail": "Database connection failed."}
