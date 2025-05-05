"""Defines tests for the references router."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import HttpUrl
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.domain.references import routes as references
from app.domain.references.models.models import (
    EnhancementRequestStatus,
    Visibility,
)
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.routes import robots
from app.domain.robots import Robots
from app.main import not_found_exception_handler

# Use the database session in all tests to set up the database manager.
pytestmark = pytest.mark.usefixtures("session")

ROBOT_ID = uuid.uuid4()
ROBOT_URL = "http://www.test-robot-here.com/"


@pytest.fixture
def app() -> FastAPI:
    """
    Create a FastAPI application instance for testing.

    Returns:
        FastAPI: FastAPI application instance.

    """
    app = FastAPI(exception_handlers={NotFoundError: not_found_exception_handler})

    app.include_router(references.router)
    app.dependency_overrides[robots] = Robots({ROBOT_ID: HttpUrl(ROBOT_URL)})

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
    session: AsyncSession, client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """Test requesting an existing reference be enhanced."""
    # Create a reference to request enhancement against
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()

    # Mock the robot response
    httpx_mock.add_response(
        method="POST", url=ROBOT_URL, status_code=status.HTTP_202_ACCEPTED
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{ROBOT_ID}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.ACCEPTED


async def test_request_reference_enhancement_robot_rejects_request(
    session: AsyncSession, client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """Test requesting enhancement to a robot that rejects the request."""
    # Create a reference to request enhancement against
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()

    # Mock the robot response
    httpx_mock.add_response(
        method="POST",
        url=ROBOT_URL,
        status_code=status.HTTP_418_IM_A_TEAPOT,
        json={"message": "broken"},
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{ROBOT_ID}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/", json=enhancement_request_create
    )

    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.REJECTED
    assert data.error == "broken"


async def test_not_found_exception_handler_returns_response_with_404(
    session: AsyncSession, client: AsyncClient
) -> None:
    """
    Test requesting reference enhancement from an unknown robot.

    Triggers the exception handler for NotFoundErrors.
    """
    unknown_robot_id = uuid.uuid4()

    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{unknown_robot_id}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "robot".casefold() in response.json()["detail"].casefold()


async def test_request_reference_enhancement_nonexistent_reference(
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

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "reference".casefold() in response.json()["detail"].casefold()


async def test_check_enhancement_request_status_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test checking the status of an enhancement request."""
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.COMPLETED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    response = await client.get(
        f"/references/enhancement/request/{enhancement_request.id}/"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.COMPLETED
