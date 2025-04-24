"""Defines tests for the references router."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references import routes as references
from app.domain.references.models.models import (
    EnhancementRequestStatus,
    Visibility,
)
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import Reference as SQLReference

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
    app.include_router(references.router)
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


async def test_register_reference(session: AsyncSession, client: AsyncClient) -> None:
    """Test registering a reference."""
    response = await client.post("/references/")

    assert response.status_code == status.HTTP_201_CREATED
    data = await session.get(SQLReference, response.json()["id"])
    assert data is not None


async def test_request_reference_enhancement_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test requesting an existing reference be enhanced."""
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{uuid.uuid4()}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.ACCEPTED


async def test_request_reference_enhancement_nonexistent_referece(
    client: AsyncClient,
) -> None:
    """Test requesting a nonexistent reference be enhanced."""
    fake_reference_id = uuid.uuid4()

    enhancement_request_create = {
        "reference_id": f"{fake_reference_id}",
        "robot_id": f"{uuid.uuid4()}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/", json=enhancement_request_create
    )

    response.json()["detail"]
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "reference".casefold() in response.json()["detail"].casefold()
