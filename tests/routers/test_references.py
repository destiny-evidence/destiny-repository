"""Defines tests for the references router."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import UUID4
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import (
    es_malformed_exception_handler,
    invalid_payload_exception_handler,
    not_found_exception_handler,
    sdk_to_domain_exception_handler,
)
from app.core.exceptions import (
    ESMalformedDocumentError,
    NotFoundError,
    SDKToDomainError,
    WrongReferenceError,
)
from app.domain.references import routes as references
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import (
    BatchEnhancementRequestStatus,
    EnhancementRequestStatus,
    EnhancementType,
    Visibility,
)
from app.domain.references.models.sql import (
    EnhancementRequest as SQLEnhancementRequest,
)
from app.domain.references.models.sql import (
    ExternalIdentifier,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.service import ReferenceService
from app.domain.robots.models.sql import Robot as SQLRobot
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
            SDKToDomainError: sdk_to_domain_exception_handler,
            WrongReferenceError: invalid_payload_exception_handler,
            ESMalformedDocumentError: es_malformed_exception_handler,
        }
    )

    app.include_router(references.reference_router, prefix="/v1")
    app.include_router(references.enhancement_request_router, prefix="/v1")

    return app


@pytest.fixture
async def client(
    app: FastAPI,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> AsyncGenerator[AsyncClient]:
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


async def add_robot(session: AsyncSession) -> SQLRobot:
    """Add a robot to the database."""
    robot = SQLRobot(
        base_url="http://www.test-robot-here.com/",
        client_secret="secret-secret",
        description="description",
        name="name",
        owner="owner",
    )
    session.add(robot)
    await session.commit()
    return robot


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


async def test_request_reference_enhancement_happy_path(
    session: AsyncSession, client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """Test requesting an existing reference be enhanced."""
    # Create a reference to request enhancement against
    reference = await add_reference(session)
    robot = await add_robot(session)

    # Mock the robot response
    httpx_mock.add_response(
        method="POST",
        url=robot.base_url + "single/",
        status_code=status.HTTP_202_ACCEPTED,
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{robot.id}",
        "enhancement_parameters": {"some": "parameters"},
    }

    response = await client.post(
        "/v1/enhancement-requests/single-requests/", json=enhancement_request_create
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
    robot = await add_robot(session)

    # Mock the robot response
    httpx_mock.add_response(
        method="POST",
        url=robot.base_url + "single/",
        status_code=status.HTTP_418_IM_A_TEAPOT,
        json={"message": "broken"},
    )

    enhancement_request_create = {
        "reference_id": f"{reference.id}",
        "robot_id": f"{robot.id}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/v1/enhancement-requests/single-requests/", json=enhancement_request_create
    )

    data = await session.get(SQLEnhancementRequest, response.json()["id"])
    assert data.request_status == EnhancementRequestStatus.REJECTED
    assert data.error == '{"message":"broken"}'


async def test_not_found_exception_handler_returns_response_with_422(
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
        "/v1/enhancement-requests/single-requests/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "robot".casefold() in response.json()["detail"].casefold()


async def test_request_reference_enhancement_nonexistent_reference(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test requesting a nonexistent reference be enhanced."""
    robot = await add_robot(session)
    fake_reference_id = uuid.uuid4()

    enhancement_request_create = {
        "reference_id": f"{fake_reference_id}",
        "robot_id": f"{robot.id}",
        "enhancement_parameters": {"some": "parametrs"},
    }

    response = await client.post(
        "/v1/enhancement-requests/single-requests/", json=enhancement_request_create
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "reference".casefold() in response.json()["detail"].casefold()


async def test_check_enhancement_request_status_happy_path(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test checking the status of an enhancement request."""
    reference = await add_reference(session)
    robot = await add_robot(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.COMPLETED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    response = await client.get(
        f"/v1/enhancement-requests/single-requests/{enhancement_request.id}/"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.COMPLETED


async def test_fulfill_enhancement_request_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,
) -> None:
    """Test creating an enhancement from a robot."""
    reference = await add_reference(session)
    await (ReferenceDocument.from_domain(reference.to_domain())).save(using=es_client)
    robot = await add_robot(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = robot_result_enhancement(enhancement_request.id, reference.id)

    response = await client.post(
        "/v1/enhancement-requests/single-requests/{enhancement_request.id}/results/",
        json=robot_result,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["request_status"] == EnhancementRequestStatus.COMPLETED

    es_reference = await ReferenceDocument.get(str(reference.id), using=es_client)
    assert es_reference
    assert (
        es_reference.enhancements[0].content == robot_result["enhancement"]["content"]
    )


async def test_fulfill_enhancement_request_robot_has_errors(
    session: AsyncSession, client: AsyncClient
) -> None:
    """Test handling a robot that fails to fulfill an enhancement request."""
    reference = await add_reference(session)
    robot = await add_robot(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = {
        "request_id": f"{enhancement_request.id}",
        "error": {"message": "Could not fulfill this enhancement request."},
    }

    response = await client.post(
        "/v1/enhancement-requests/single-requests/{enhancement_request.id}/results/",
        json=robot_result,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["request_status"] == EnhancementRequestStatus.FAILED


async def test_wrong_reference_exception_handler_returns_response_with_400(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test handling a robot that fails to fulfill an enhancement request."""
    reference = await add_reference(session)
    different_reference = await add_reference(session)
    robot = await add_robot(session)

    enhancement_request = SQLEnhancementRequest(
        reference_id=reference.id,
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.ACCEPTED,
        enhancement_parameters={},
    )
    session.add(enhancement_request)
    await session.commit()

    robot_result = robot_result_enhancement(
        enhancement_request.id, different_reference.id
    )

    response = await client.post(
        "/v1/enhancement-requests/single-requests/{enhancement_request.id}/results/",
        json=robot_result,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_request_batch_enhancement_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch enhancement for multiple references."""
    # Add references to the database
    reference_1 = await add_reference(session)
    reference_2 = await add_reference(session)
    robot = await add_robot(session)
    batch_request_create = {
        "reference_ids": [str(reference_1.id), str(reference_2.id)],
        "robot_id": f"{robot.id}",
    }

    mock_process = AsyncMock(return_value=None)
    monkeypatch.setattr(
        ReferenceService,
        "collect_and_dispatch_references_for_batch_enhancement",
        mock_process,
    )

    with patch("app.core.telemetry.fastapi.bound_contextvars") as mock_bound:
        response = await client.post(
            "/v1/enhancement-requests/batch-requests/", json=batch_request_create
        )
        found = any(
            "robot_id" in call.kwargs and call.kwargs["robot_id"] == str(robot.id)
            for call in mock_bound.call_args_list
        )
        assert found, "Expected 'robot_id' to be set in structlog contextvars"
        assert response.status_code == status.HTTP_202_ACCEPTED
        response_data = response.json()
    assert "id" in response_data
    assert response_data["request_status"] == BatchEnhancementRequestStatus.RECEIVED
    assert response_data["reference_ids"] == [str(reference_1.id), str(reference_2.id)]

    assert isinstance(broker, InMemoryBroker)
    await broker.wait_all()
    mock_process.assert_awaited_once()


async def test_add_robot_automation_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test adding a robot automation."""
    robot = await add_robot(session)

    robot_automation_create = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": str(robot.id)}},
    }

    with patch("app.core.telemetry.fastapi.bound_contextvars") as mock_bound:
        response = await client.post(
            "/v1/enhancement-requests/automations/", json=robot_automation_create
        )
        found = any(
            "robot_id" in call.kwargs and call.kwargs["robot_id"] == str(robot.id)
            for call in mock_bound.call_args_list
        )
        assert found, "Expected 'robot_id' to be set in structlog contextvars"
        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
    assert uuid.UUID(response_data["robot_id"]) == robot.id
    assert response_data["query"] == robot_automation_create["query"]


async def test_add_robot_automation_missing_robot(
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test adding a robot automation with a missing robot."""
    robot_automation_create = {
        "robot_id": str(uuid.uuid4()),
        "query": {"match": {"robot_id": "some-robot-id"}},
    }

    response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "robot" in response.json()["detail"].casefold()


async def test_add_robot_automation_invalid_query(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test adding a robot automation with an invalid query."""
    robot = await add_robot(session)

    robot_automation_create = {
        "robot_id": str(robot.id),
        "query": {"invalid": "query"},
    }

    response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "DSL class `invalid` does not exist in query" in response.json()["detail"]

    robot_automation_create = {
        "robot_id": str(robot.id),
        "query": {"match": {"invalid": "value"}},
    }

    response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "No field mapping can be found for the field with name [invalid]"
        in response.json()["detail"]
    )


async def test_get_reference_by_identifier_fails_with_404(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test retrieving a reference by its identifier."""
    reference = await add_reference(session)
    session.add(
        ExternalIdentifier(
            reference_id=reference.id,
            identifier="10.1234/example",
            identifier_type="doi",
        )
    )

    response = await client.get(
        "/v1/references/",
        params={"identifier": "10.1234/example", "identifier_type": "doi"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    response_data = response.json()
    assert (
        response_data["detail"] == "ExternalIdentifier with external_identifier ("
        "<ExternalIdentifierType.DOI: 'doi'>, '10.1234/example', None) does not exist."
    )


async def test_update_robot_automation_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test updating a robot automation."""
    robot = await add_robot(session)

    # First create an automation
    robot_automation_create = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": str(robot.id)}},
    }

    create_response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    automation_id = create_response.json()["id"]

    # Now update the automation
    robot_automation_update = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": "updated_query"}},
    }

    response = await client.put(
        f"/v1/enhancement-requests/automations/{automation_id}/",
        json=robot_automation_update,
    )

    assert response.status_code == status.HTTP_201_CREATED
    response_data = response.json()
    assert uuid.UUID(response_data["robot_id"]) == robot.id
    assert response_data["query"] == robot_automation_update["query"]
    assert uuid.UUID(response_data["id"]) == uuid.UUID(automation_id)


async def test_update_robot_automation_nonexistent_automation(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test updating a nonexistent robot automation."""
    robot = await add_robot(session)
    fake_automation_id = uuid.uuid4()

    robot_automation_update = {
        "robot_id": str(robot.id),
        "query": {"match": {"name": "updated_query"}},
    }

    response = await client.put(
        f"/v1/enhancement-requests/automations/{fake_automation_id}/",
        json=robot_automation_update,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "automation" in response.json()["detail"].casefold()


async def test_update_robot_automation_missing_robot(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test updating a robot automation with a missing robot."""
    robot = await add_robot(session)

    # First create an automation
    robot_automation_create = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": str(robot.id)}},
    }

    create_response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    automation_id = create_response.json()["id"]

    # Now try to update with a nonexistent robot
    fake_robot_id = uuid.uuid4()
    robot_automation_update = {
        "robot_id": str(fake_robot_id),
        "query": {"match": {"name": "updated_query"}},
    }

    response = await client.put(
        f"/v1/enhancement-requests/automations/{automation_id}/",
        json=robot_automation_update,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "robot" in response.json()["detail"].casefold()


async def test_get_robot_automations_empty_list(
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test getting robot automations when there are none."""
    response = await client.get("/v1/enhancement-requests/automations/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


async def test_get_robot_automations_with_automations(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test getting robot automations when there are some."""
    robot = await add_robot(session)

    # Create first automation
    robot_automation_create_1 = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": "robot uno"}},
    }

    create_response_1 = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create_1
    )
    assert create_response_1.status_code == status.HTTP_201_CREATED

    # Create second automation
    robot_automation_create_2 = {
        "robot_id": str(robot.id),
        "query": {"match": {"robot_id": "robot dos"}},
    }

    create_response_2 = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create_2
    )
    assert create_response_2.status_code == status.HTTP_201_CREATED

    # Get all automations
    response = await client.get("/v1/enhancement-requests/automations/")

    assert response.status_code == status.HTTP_200_OK
    response_data = response.json()
    assert len(response_data) == 2

    # Check that both automations are returned
    automation_ids = {automation["id"] for automation in response_data}
    expected_ids = {create_response_1.json()["id"], create_response_2.json()["id"]}
    assert automation_ids == expected_ids

    # Check robot IDs are correct
    robot_ids = {uuid.UUID(automation["robot_id"]) for automation in response_data}
    expected_robot_ids = {robot.id, robot.id}
    assert robot_ids == expected_robot_ids
