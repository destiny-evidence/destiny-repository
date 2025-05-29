"""Defines tests for the references router."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import UUID4
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.core.exceptions import (
    NotFoundError,
    SDKToDomainError,
    WrongReferenceError,
)
from app.domain.references import routes as references
from app.domain.references.models.models import (
    BatchEnhancementRequestStatus,
    EnhancementRequestStatus,
    EnhancementType,
    Visibility,
)
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.routes import robots
from app.domain.references.service import ReferenceService
from app.domain.robots.models import RobotConfig
from app.domain.robots.service import RobotService
from app.main import (
    enhance_wrong_reference_exception_handler,
    not_found_exception_handler,
    sdk_to_domain_exception_handler,
)
from app.tasks import broker

# Use the database session in all tests to set up the database manager.
pytestmark = pytest.mark.usefixtures("session")

ROBOT_ID = uuid.uuid4()
ROBOT_URL = "http://www.test-robot-here.com/"
FAKE_ROBOT_TOKEN = "access_token"


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
            SDKToDomainError: sdk_to_domain_exception_handler,
            WrongReferenceError: enhance_wrong_reference_exception_handler,
        }
    )

    app.include_router(references.router)
    app.include_router(references.robot_router)
    app.dependency_overrides[robots] = RobotService(
        [
            RobotConfig(
                robot_id=ROBOT_ID,
                robot_url=ROBOT_URL,
                dependent_enhancements=[],
                dependent_identifiers=[],
                communication_secret_name="secret-secret",
            )
        ]
    )

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


async def add_reference(session: AsyncSession) -> SQLReference:
    """Add a reference to the database."""
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()
    return reference


def robot_result_enhancement(
    enhancement_request_id: UUID4, reference_id: UUID4
) -> dict:
    """Construct a RobotResult for creating ehancments."""
    return {
        "request_id": f"{enhancement_request_id}",
        "enhancement": {
            "reference_id": f"{reference_id}",
            "source": "robot",
            "visibility": Visibility.RESTRICTED,
            "robot_version": "0.0.1",
            "content_version": f"{uuid.uuid4()}",
            "content": {
                "enhancement_type": EnhancementType.ANNOTATION,
                "annotations": [
                    {
                        "scheme": "example:toy",
                        "annotation_type": "boolean",
                        "value": True,
                        "label": "toy",
                        "data": {"toy": "Cabbage Patch Kid"},
                    }
                ],
            },
        },
    }


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
    reference = await add_reference(session)

    # Mock the robot response
    httpx_mock.add_response(
        method="POST", url=ROBOT_URL + "single/", status_code=status.HTTP_202_ACCEPTED
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{ROBOT_ID}",
        "enhancement_parameters": {"some": "parameters"},
    }

    response = await client.post(
        "/references/enhancement/single/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.ACCEPTED


async def test_request_reference_enhancement_robot_rejects_request(
    session: AsyncSession, client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """Test requesting enhancement to a robot that rejects the request."""
    # Create a reference to request enhancement against
    reference = await add_reference(session)

    # Mock the robot response
    httpx_mock.add_response(
        method="POST",
        url=ROBOT_URL + "single/",
        status_code=status.HTTP_418_IM_A_TEAPOT,
        json={"message": "broken"},
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{ROBOT_ID}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/single/", json=enhancement_request_create
    )

    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.REJECTED
    assert data.error == '{"message":"broken"}'


async def test_not_found_exception_handler_returns_response_with_404(
    session: AsyncSession, client: AsyncClient
) -> None:
    """
    Test requesting reference enhancement from an unknown robot.

    Triggers the exception handler for NotFoundErrors.
    """
    unknown_robot_id = uuid.uuid4()

    reference = await add_reference(session)

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{unknown_robot_id}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/references/enhancement/single/", json=enhancement_request_create
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
        "/references/enhancement/single/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "reference".casefold() in response.json()["detail"].casefold()


async def test_check_enhancement_request_status_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test checking the status of an enhancement request."""
    reference = await add_reference(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.COMPLETED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    response = await client.get(
        f"/references/enhancement/single/request/{enhancement_request.id}/"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.COMPLETED


async def test_fulfill_enhancement_request_happy_path(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test creating an enhancement from a robot."""
    reference = await add_reference(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = robot_result_enhancement(enhancement_request.id, reference.id)

    response = await client.post("/robot/enhancement/single/", json=robot_result)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.COMPLETED


async def test_fulfill_enhancement_request_robot_has_errors(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test handling a robot that fails to fulfill an enhancement request."""
    reference = await add_reference(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = {
        "request_id": f"{enhancement_request.id}",
        "error": {"message": "Could not fulfill this enhancement request."},
    }

    response = await client.post("/robot/enhancement/single/", json=robot_result)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.FAILED


async def test_wrong_reference_exception_handler_returns_response_with_400(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test handling a robot that fails to fulfill an enhancement request."""
    reference = await add_reference(session)
    different_reference = await add_reference(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = robot_result_enhancement(
        enhancement_request.id, different_reference.id
    )

    response = await client.post("/robot/enhancement/single/", json=robot_result)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


async def test_request_batch_enhancement_happy_path(
    session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test requesting a batch enhancement for multiple references."""
    # Add references to the database
    reference_1 = await add_reference(session)
    reference_2 = await add_reference(session)

    batch_request_create = {
        "reference_ids": [str(reference_1.id), str(reference_2.id)],
        "robot_id": str(uuid.uuid4()),
    }

    response = await client.post(
        "/references/enhancement/batch/", json=batch_request_create
    )

    mock_process = AsyncMock(return_value=None)
    monkeypatch.setattr(
        ReferenceService,
        "collect_and_dispatch_references_for_batch_enhancement",
        mock_process,
    )

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert "id" in response_data
    assert response_data["request_status"] == BatchEnhancementRequestStatus.RECEIVED
    assert response_data["reference_ids"] == [str(reference_1.id), str(reference_2.id)]

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()
    mock_process.assert_awaited_once()
