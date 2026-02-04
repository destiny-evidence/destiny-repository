"""Defines tests for the references router."""

import datetime
from collections.abc import AsyncGenerator
from unittest.mock import ANY, AsyncMock, patch
from uuid import UUID, uuid7

import pytest
from destiny_sdk.enhancements import EnhancementType
from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import InMemoryBroker

from app.api.exception_handlers import (
    es_exception_handler,
    invalid_payload_exception_handler,
    not_found_exception_handler,
    parse_error_exception_handler,
    sdk_to_domain_exception_handler,
)
from app.core.config import get_settings
from app.core.exceptions import (
    ESMalformedDocumentError,
    ESQueryError,
    InvalidPayloadError,
    NotFoundError,
    ParseError,
    SDKToDomainError,
)
from app.domain.references import routes as references
from app.domain.references.models.models import (
    EnhancementRequestStatus,
    PendingEnhancementStatus,
    Visibility,
)
from app.domain.references.models.models import Reference as DomainReference
from app.domain.references.models.sql import Enhancement as SQLEnhancement
from app.domain.references.models.sql import EnhancementRequest as SQLEnhancementRequest
from app.domain.references.models.sql import (
    ExternalIdentifier,
)
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.models.sql import (
    RobotEnhancementBatch as SQLRobotEnhancementBatch,
)
from app.domain.references.service import ReferenceService
from app.domain.robots.models.sql import Robot as SQLRobot
from app.persistence.blob.models import BlobSignedUrlType, BlobStorageFile
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.persistence import ESSearchResult, ESSearchTotal
from app.tasks import broker
from app.utils.time_and_date import apply_positive_timedelta, iso8601_duration_adapter
from tests.factories import (
    ReferenceFactory,
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
    app = FastAPI(
        exception_handlers={
            NotFoundError: not_found_exception_handler,
            SDKToDomainError: sdk_to_domain_exception_handler,
            InvalidPayloadError: invalid_payload_exception_handler,
            ESMalformedDocumentError: es_exception_handler,
            ESQueryError: es_exception_handler,
            ParseError: parse_error_exception_handler,
        }
    )

    app.include_router(references.reference_router, prefix="/v1")
    app.include_router(references.enhancement_request_router, prefix="/v1")
    app.include_router(references.robot_enhancement_batch_router, prefix="/v1")

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


@pytest.fixture
def mock_blob_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a mock blob repository for generating signed urls."""

    class MockBlobRepository(BlobRepository):
        async def get_signed_url(
            self,
            file: BlobStorageFile,
            interaction_type: BlobSignedUrlType,
        ) -> HttpUrl:
            return HttpUrl(f"http://signed/{file.filename}/{interaction_type}")

    monkeypatch.setattr(
        references,
        "BlobRepository",
        MockBlobRepository,
    )


async def add_reference(session: AsyncSession) -> SQLReference:
    """Add a reference to the database."""
    reference = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference)
    await session.commit()
    return reference


async def add_robot(session: AsyncSession) -> SQLRobot:
    """Add a robot to the database."""
    robot = SQLRobot(
        client_secret="secret-secret",
        description="description",
        name="name",
        owner="owner",
    )
    session.add(robot)
    await session.commit()
    return robot


async def add_enhancement_request(
    session: AsyncSession, robot: SQLRobot, reference: SQLReference
) -> SQLEnhancementRequest:
    """Add an enhancement request to the database."""
    enhancement_request = SQLEnhancementRequest(
        reference_ids=[reference.id],
        robot_id=robot.id,
        request_status=EnhancementRequestStatus.RECEIVED,
    )
    session.add(enhancement_request)
    await session.commit()
    return enhancement_request


async def add_pending_enhancement(
    session: AsyncSession,
    reference: SQLReference,
    enhancement_request: SQLEnhancementRequest,
) -> SQLPendingEnhancement:
    """Add a pending enhancement to the database."""
    pending_enhancement = SQLPendingEnhancement(
        reference_id=reference.id,
        robot_id=enhancement_request.robot_id,
        enhancement_request_id=enhancement_request.id,
        status=PendingEnhancementStatus.PENDING,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=10),
    )
    session.add(pending_enhancement)
    await session.commit()
    return pending_enhancement


async def add_robot_enhancement_batch(
    session: AsyncSession, pending_enhancement: SQLPendingEnhancement
):
    """Add a robot enhancement batch to the database."""
    robot_enhancement_batch = SQLRobotEnhancementBatch(
        robot_id=pending_enhancement.robot_id,
        pending_enhancements=[pending_enhancement],
        reference_data_file="minio://destiny-repository/robot_enhancement_batch_reference_data/some_fake_reference_data.jsonl",
        result_file="minio://destiny-repository/enhancement_result/some_fake_enhancement_results.jsonl",
    )
    pending_enhancement.robot_enhancement_batch_id = robot_enhancement_batch.id

    session.add(robot_enhancement_batch)
    session.add(pending_enhancement)
    await session.commit()
    return robot_enhancement_batch.to_domain()


async def add_enhancement(session: AsyncSession, reference_id: UUID):
    """Add a basic enhancement to a reference."""
    enhancement = SQLEnhancement(
        id=uuid7(),
        reference_id=reference_id,
        visibility=Visibility.PUBLIC,
        source="test_source",
        enhancement_type=EnhancementType.ANNOTATION,
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "test:scheme",
                    "label": "test_label",
                    "value": True,
                }
            ],
        },
    )

    session.add(enhancement)
    await session.commit()
    return enhancement


async def test_get_reference_with_enhancements_happy_path(
    session: AsyncSession, client: AsyncClient
):
    """Test requesting a single reference by id."""
    reference = await add_reference(session)
    enhancement = await add_enhancement(session, reference.id)

    response = await client.get(f"/v1/references/{reference.id}/")

    response_data = response.json()

    assert UUID(response_data["id"]) == reference.id
    assert UUID(response_data["enhancements"][0]["id"]) == enhancement.id


async def test_request_batch_enhancement_happy_path(
    session: AsyncSession,
    client: AsyncClient,
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
    assert UUID(response_data["robot_id"]) == robot.id
    assert response_data["query"] == robot_automation_create["query"]


async def test_add_robot_automation_missing_robot(
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test adding a robot automation with a missing robot."""
    robot_automation_create = {
        "robot_id": str(uuid7()),
        "query": {"match": {"robot_id": "some-robot-id"}},
    }

    response = await client.post(
        "/v1/enhancement-requests/automations/", json=robot_automation_create
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
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
    assert UUID(response_data["robot_id"]) == robot.id
    assert response_data["query"] == robot_automation_update["query"]
    assert UUID(response_data["id"]) == UUID(automation_id)


async def test_update_robot_automation_nonexistent_automation(
    session: AsyncSession,
    client: AsyncClient,
    es_client: AsyncElasticsearch,  # noqa: ARG001
) -> None:
    """Test updating a nonexistent robot automation."""
    robot = await add_robot(session)
    fake_automation_id = uuid7()

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
    fake_robot_id = uuid7()
    robot_automation_update = {
        "robot_id": str(fake_robot_id),
        "query": {"match": {"name": "updated_query"}},
    }

    response = await client.put(
        f"/v1/enhancement-requests/automations/{automation_id}/",
        json=robot_automation_update,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
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
    robot_ids = {UUID(automation["robot_id"]) for automation in response_data}
    expected_robot_ids = {robot.id, robot.id}
    assert robot_ids == expected_robot_ids


async def test_request_robot_enhancement_batch(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    mock_blob_repository: None,  # noqa: ARG001
) -> None:
    """Test requesting a batch of pending enhancements for a robot."""
    # Set up test data
    robot = await add_robot(session)
    reference = await add_reference(session)
    enhancement_request = await add_enhancement_request(session, robot, reference)
    pending_enhancement = await add_pending_enhancement(
        session, reference, enhancement_request
    )
    robot_enhancement_batch = await add_robot_enhancement_batch(
        session, pending_enhancement
    )

    mock_get_pending = AsyncMock(return_value=[pending_enhancement])
    mock_create_batch = AsyncMock(return_value=robot_enhancement_batch)

    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )
    monkeypatch.setattr(
        ReferenceService, "create_robot_enhancement_batch", mock_create_batch
    )

    response = await client.post(
        f"/v1/robot-enhancement-batches/?robot_id={robot.id}&limit=10&lease=PT5M"
    )

    assert response.status_code == status.HTTP_200_OK
    mock_get_pending.assert_awaited_once_with(robot_id=robot.id, limit=10)

    mock_create_batch.assert_awaited_once_with(
        robot_id=robot.id,
        pending_enhancements=[pending_enhancement],
        lease_duration=datetime.timedelta(minutes=5),
        blob_repository=ANY,
    )


async def test_request_robot_enhancement_batch_no_pending_enhancements(
    session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch when there are no pending enhancements."""
    robot = await add_robot(session)

    mock_get_pending = AsyncMock(return_value=[])
    mock_create_batch = AsyncMock()
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )
    monkeypatch.setattr(
        ReferenceService, "create_robot_enhancement_batch", mock_create_batch
    )

    response = await client.post(
        f"/v1/robot-enhancement-batches/?robot_id={robot.id}&limit=10"
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_get_pending.assert_awaited_once_with(robot_id=robot.id, limit=10)
    mock_create_batch.assert_not_awaited()


async def test_request_robot_enhancement_batch_limit_exceeded(
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
        f"/v1/robot-enhancement-batches/?robot_id={robot.id}&limit=99999"
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    # Should be called with the default max limit, not the requested limit
    mock_get_pending.assert_awaited_once()
    call_args = mock_get_pending.call_args
    assert call_args.kwargs["limit"] == 10000  # Should be capped at max limit


async def test_request_robot_enhancement_batch_invalid_robot_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch with invalid robot ID format."""
    mock_get_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )

    response = await client.post(
        "/v1/robot-enhancement-batches/?robot_id=invalid-uuid&limit=10"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    mock_get_pending.assert_not_awaited()


async def test_request_robot_enhancement_batch_missing_robot_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test requesting a batch without robot_id parameter."""
    mock_get_pending = AsyncMock(return_value=[])
    monkeypatch.setattr(
        ReferenceService, "get_pending_enhancements_for_robot", mock_get_pending
    )

    response = await client.post("/v1/robot-enhancement-batches/?limit=10")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    mock_get_pending.assert_not_awaited()


async def test_get_robot_enhancement_batch_happy_path(
    session: AsyncSession,
    client: AsyncClient,
    mock_blob_repository: None,  # noqa: ARG001
):
    """Test getting an existing robot batch by id."""
    robot = await add_robot(session)
    reference = await add_reference(session)
    enhancement_request = await add_enhancement_request(session, robot, reference)
    pending_enhancement = await add_pending_enhancement(
        session, reference, enhancement_request
    )
    robot_enhancement_batch = await add_robot_enhancement_batch(
        session, pending_enhancement
    )

    response = await client.get(
        f"/v1/robot-enhancement-batches/{robot_enhancement_batch.id}/"
    )

    assert response.status_code == status.HTTP_200_OK

    response_data = response.json()
    assert response_data["id"] == str(robot_enhancement_batch.id)
    assert "signed" in response_data["reference_storage_url"]


async def test_lookup_references_multiple_identifiers(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test lookup_references with multiple identifiers of different types."""
    # Add a reference with a UUID
    reference = await add_reference(session)
    # Add a reference with a DOI identifier (simulate by setting external identifier)
    doi_identifier = "10.1000/abc123"
    reference_doi = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference_doi)
    await session.commit()
    # Simulate ExternalIdentifier for DOI
    external_identifier = ExternalIdentifier(
        reference_id=reference_doi.id,
        identifier=doi_identifier,
        identifier_type="doi",
    )
    session.add(external_identifier)
    await session.commit()

    identifiers = [str(reference.id), f"doi:{doi_identifier}"]
    response = await client.get(
        "/v1/references/",
        params={
            "identifier": identifiers,
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    returned_ids = {item["id"] for item in data}
    assert str(reference.id) in returned_ids
    assert str(reference_doi.id) in returned_ids


async def test_lookup_references_accepts_csv(
    session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Test lookup_references accepts comma-separated identifiers."""
    # Add a reference with a UUID
    reference = await add_reference(session)
    # Add a reference with a DOI identifier (simulate by setting external identifier)
    doi_identifier = "10.1000/abc123"
    reference_doi = SQLReference(visibility=Visibility.RESTRICTED)
    session.add(reference_doi)
    await session.commit()
    # Simulate ExternalIdentifier for DOI
    external_identifier = ExternalIdentifier(
        reference_id=reference_doi.id,
        identifier=doi_identifier,
        identifier_type="doi",
    )
    session.add(external_identifier)
    await session.commit()

    response = await client.get(
        "/v1/references/",
        params={
            "identifier": f"{reference.id},doi:{doi_identifier}",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    returned_ids = {item["id"] for item in data}
    assert str(reference.id) in returned_ids
    assert str(reference_doi.id) in returned_ids


async def test_lookup_references_too_many_identifiers(
    client: AsyncClient,
) -> None:
    """Test lookup_references with too many identifiers."""
    too_many_identifiers = [
        str(uuid7())
        for _ in range(get_settings().max_lookup_reference_query_length + 1)
    ]
    response = await client.get(
        "/v1/references/",
        params={"identifier": too_many_identifiers},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    response = await client.get(
        "/v1/references/",
        params={"identifier": ",".join(too_many_identifiers)},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_lookup_references_invalid_identifier_format(
    client: AsyncClient,
) -> None:
    """Test lookup_references with an invalid identifier format."""
    invalid_identifier = "not-a-uuid"
    response = await client.get(
        "/v1/references/",
        params={"identifier": invalid_identifier},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Must be UUID" in response.text


async def test_get_robot_enhancement_batch_nonexistent_batch(client: AsyncClient):
    """Test getting a robot enhancement batch that does not exist."""
    response = await client.get(f"/v1/robot-enhancement-batces/{uuid7()}/")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_robot_enhancement_batch_renew_lease(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test renewing a lease on a robot enhancement batch."""
    dt = datetime.timedelta(minutes=5)
    dt_iso = iso8601_duration_adapter.dump_python(dt, mode="json")
    expiry = apply_positive_timedelta(dt)
    mock_renew_lease = AsyncMock(return_value=(5, expiry))
    monkeypatch.setattr(
        ReferenceService, "renew_robot_enhancement_batch_lease", mock_renew_lease
    )

    _id = uuid7()
    response = await client.patch(
        f"/v1/robot-enhancement-batches/{_id}/renew-lease/?lease={dt_iso}"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.text == expiry.isoformat()

    mock_renew_lease.assert_awaited_once_with(
        robot_enhancement_batch_id=_id,
        lease_duration=dt,
    )


async def test_robot_enhancement_batch_renew_lease_empty_response(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test renewing a lease on a robot enhancement batch with no renewals left."""
    dt = datetime.timedelta(minutes=5)
    dt_iso = iso8601_duration_adapter.dump_python(dt, mode="json")
    expiry = apply_positive_timedelta(dt)
    mock_renew_lease = AsyncMock(return_value=(0, expiry))
    monkeypatch.setattr(
        ReferenceService, "renew_robot_enhancement_batch_lease", mock_renew_lease
    )

    _id = uuid7()
    response = await client.patch(
        f"/v1/robot-enhancement-batches/{_id}/renew-lease/?lease={dt_iso}"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert (
        response.json()["detail"] == "This batch has no pending enhancements. "
        "They may have already expired or been completed."
    )

    mock_renew_lease.assert_awaited_once_with(
        robot_enhancement_batch_id=_id,
        lease_duration=dt,
    )


async def test_search_references_with_annotation_filters(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that annotation filters are correctly parsed and passed to the service."""
    reference = ReferenceFactory.build()

    # Create a mock search result
    mock_search_result = ESSearchResult[DomainReference](
        hits=[reference],
        total=ESSearchTotal(value=1, relation="eq"),
        page=1,
    )

    # Mock the service method
    # Temporary patch until ES itself includes annotations
    mock_search = AsyncMock(return_value=mock_search_result)
    monkeypatch.setattr(ReferenceService, "search_references", mock_search)

    # Test with annotation filters
    response = await client.get(
        "/v1/references/search/",
        params={
            "q": "test",
            "annotation": [
                "test:scheme/test_label",
                "another:scheme/another_label@0.8",
                "just_a_scheme@0.8",
                "test:scheme/label/with/lots/of/slashes",
            ],
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"]["count"] == 1

    # Verify the service was called with the correct annotation filters
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["annotations"] is not None
    assert len(call_kwargs["annotations"]) == 4

    # Check first annotation filter
    assert call_kwargs["annotations"][0].scheme == "test:scheme"
    assert call_kwargs["annotations"][0].label == "test_label"
    assert call_kwargs["annotations"][0].score is None

    # Check second annotation filter with score
    assert call_kwargs["annotations"][1].scheme == "another:scheme"
    assert call_kwargs["annotations"][1].label == "another_label"
    assert call_kwargs["annotations"][1].score == 0.8

    # Check third annotation filter without label is ignored
    assert call_kwargs["annotations"][2].scheme == "just_a_scheme"
    assert not call_kwargs["annotations"][2].label
    assert call_kwargs["annotations"][2].score == 0.8

    # Check fourth annotation filter with slashes in label
    assert call_kwargs["annotations"][3].scheme == "test:scheme"
    assert call_kwargs["annotations"][3].label == "label/with/lots/of/slashes"
    assert call_kwargs["annotations"][3].score is None
