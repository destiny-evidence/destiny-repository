"""Defines tests for the references router."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import UUID4
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
    InvalidPayloadError,
    NotFoundError,
    SDKToDomainError,
)
from app.domain.references import routes as references
from app.domain.references.models.models import (
    EnhancementRequestStatus,
    EnhancementType,
    PendingEnhancement,
    PendingEnhancementStatus,
    RobotEnhancementBatch,
    RobotEnhancementBatchStatus,
    Visibility,
)
from app.domain.references.models.sql import (
    EnhancementRequest,
    ExternalIdentifier,
)
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.service import ReferenceService
from app.domain.robots.models.sql import Robot as SQLRobot
from app.persistence.blob.models import BlobStorageFile
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
            InvalidPayloadError: invalid_payload_exception_handler,
            ESMalformedDocumentError: es_malformed_exception_handler,
        }
    )

    app.include_router(references.reference_router, prefix="/v1")
    app.include_router(references.enhancement_request_router, prefix="/v1")
    app.include_router(references.pending_enhancements_router, prefix="/v1")

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


async def test_request_batch_enhancement_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a enhancement for multiple references."""
    # Add references to the database
    reference_1 = await add_reference(session)
    reference_2 = await add_reference(session)
    robot = await add_robot(session)
    enhancement_request_create = {
        "reference_ids": [str(reference_1.id), str(reference_2.id)],
        "robot_id": f"{robot.id}",
    }

    mock_process = AsyncMock(return_value=None)
    monkeypatch.setattr(
        ReferenceService,
        "collect_and_dispatch_references_for_enhancement",
        mock_process,
    )

    with patch("app.core.telemetry.fastapi.bound_contextvars") as mock_bound:
        response = await client.post(
            "/v1/enhancement-requests/", json=enhancement_request_create
        )
        found = any(
            "robot_id" in call.kwargs and call.kwargs["robot_id"] == str(robot.id)
            for call in mock_bound.call_args_list
        )
        assert found, "Expected 'robot_id' to be set in structlog contextvars"
        assert response.status_code == status.HTTP_202_ACCEPTED
        response_data = response.json()
    assert "id" in response_data
    assert response_data["request_status"] == EnhancementRequestStatus.RECEIVED
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


async def add_enhancement_request(
    session: AsyncSession, robot: SQLRobot, reference: SQLReference
) -> EnhancementRequest:
    """Add an enhancement request to the database."""
    enhancement_request = EnhancementRequest(
        reference_ids=[reference.id],
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.RECEIVED,
    )
    session.add(enhancement_request)
    await session.commit()
    return enhancement_request


async def add_pending_enhancement(
    session: AsyncSession,
    robot: SQLRobot,
    reference: SQLReference,
    enhancement_request: EnhancementRequest,
) -> SQLPendingEnhancement:
    """Add a pending enhancement to the database."""
    pending_enhancement = SQLPendingEnhancement(
        reference_id=reference.id,
        robot_id=robot.id,
        enhancement_request_id=enhancement_request.id,
        status=PendingEnhancementStatus.PENDING,
    )
    session.add(pending_enhancement)
    await session.commit()
    return pending_enhancement


async def test_request_pending_enhancements_batch_no_results(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch of pending enhancements for a robot."""
    # Set up test data
    robot = await add_robot(session)
    reference = await add_reference(session)
    enhancement_request = await add_enhancement_request(session, robot, reference)
    await add_pending_enhancement(session, robot, reference, enhancement_request)

    # Mock the service methods
    mock_get_pending = AsyncMock(return_value=[])
    mock_create_batch = AsyncMock()

    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )
    monkeypatch.setattr(
        ReferenceService, "create_robot_enhancement_batch", mock_create_batch
    )

    response = await client.post(
        f"/v1/pending-enhancements/batch/?robot_id={robot.id}&limit=10"
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_get_pending.assert_awaited_once_with(robot_id=robot.id, limit=10)


async def test_request_pending_enhancements_batch_with_results(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch of pending enhancements when there are results."""
    # Set up test data
    robot = await add_robot(session)
    reference = await add_reference(session)
    enhancement_request = await add_enhancement_request(session, robot, reference)
    pending_enhancement = await add_pending_enhancement(
        session, robot, reference, enhancement_request
    )

    # Mock the service methods
    mock_pending_enhancements = [
        PendingEnhancement(
            id=pending_enhancement.id,
            reference_id=reference.id,
            robot_id=robot.id,
            enhancement_request_id=enhancement_request.id,
            status=PendingEnhancementStatus.PENDING,
        )
    ]

    mock_batch = RobotEnhancementBatch(
        id=uuid.uuid4(),
        robot_id=robot.id,
        status=RobotEnhancementBatchStatus.PENDING,
        reference_file=BlobStorageFile(
            location="minio", container="test", path="test", filename="test.jsonl"
        ),
        result_file=BlobStorageFile(
            location="minio", container="test", path="test", filename="result.jsonl"
        ),
        pending_enhancements=mock_pending_enhancements,
    )

    mock_sdk_response = {
        "id": str(uuid.uuid4()),
        "reference_storage_url": "http://example.com/references.jsonl",
        "result_storage_url": "http://example.com/results.jsonl",
        "extra_fields": None,
    }

    mock_get_pending = AsyncMock(return_value=mock_pending_enhancements)
    mock_create_batch = AsyncMock(return_value=mock_batch)
    mock_batch_to_sdk = AsyncMock(return_value=mock_sdk_response)

    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )
    monkeypatch.setattr(
        ReferenceService, "create_robot_enhancement_batch", mock_create_batch
    )

    # Mock the anti-corruption service method that converts to SDK
    from app.domain.references.services.anti_corruption_service import (
        ReferenceAntiCorruptionService,
    )

    monkeypatch.setattr(
        ReferenceAntiCorruptionService,
        "robot_enhancement_batch_to_sdk",
        mock_batch_to_sdk,
    )

    response = await client.post(
        f"/v1/pending-enhancements/batch/?robot_id={robot.id}&limit=10"
    )

    assert response.status_code == status.HTTP_200_OK
    response_data = response.json()

    # Check that the response contains expected fields from the RobotRequest schema
    assert response_data == mock_sdk_response

    mock_get_pending.assert_awaited_once_with(robot_id=robot.id, limit=10)
    mock_create_batch.assert_awaited_once()
    mock_batch_to_sdk.assert_awaited_once_with(mock_batch)


async def test_request_pending_enhancements_batch_limit_exceeded(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch with limit exceeding maximum allowed."""
    robot = await add_robot(session)

    mock_get_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )

    # Request with a very high limit
    response = await client.post(
        f"/v1/pending-enhancements/batch/?robot_id={robot.id}&limit=99999"
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    # Should be called with the default max limit, not the requested limit
    mock_get_pending.assert_awaited_once()
    call_args = mock_get_pending.call_args
    assert call_args.kwargs["limit"] == 10000  # Should be capped at max limit


async def test_request_pending_enhancements_batch_invalid_robot_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch with invalid robot ID format."""
    mock_get_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )

    response = await client.post(
        "/v1/pending-enhancements/batch/?robot_id=invalid-uuid&limit=10"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_get_pending.assert_not_awaited()


async def test_request_pending_enhancements_batch_missing_robot_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch without robot_id parameter."""
    mock_get_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )

    response = await client.post("/v1/pending-enhancements/batch/?limit=10")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_get_pending.assert_not_awaited()
