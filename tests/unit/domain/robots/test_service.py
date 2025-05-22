import uuid
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from destiny_sdk.visibility import Visibility
from fastapi import status
from pydantic import HttpUrl

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    EnhancementRequest,
    Reference,
)
from app.domain.robots.models import RobotConfig, Robots
from app.domain.robots.service import RobotService

ROBOT_ID = uuid.uuid4()
ROBOT_URL = HttpUrl("http://www.theres-a-robot-here.com/")

KNOWN_ROBOTS = [
    RobotConfig(
        robot_id=ROBOT_ID,
        robot_url=ROBOT_URL,
        dependent_enhancements=[],
        dependent_identifiers=[],
    ),
]


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_happy_path(fake_uow, httpx_mock):
    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=uuid.uuid4(),
        enhancement_parameters={},
    )

    service = RobotService(
        fake_uow(enhancement_requests=enhancement_request),
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(ROBOT_URL),
        status_code=status.HTTP_202_ACCEPTED,
    )

    await service.request_enhancement_from_robot(
        robot_url=ROBOT_URL,
        enhancement_request=enhancement_request,
        reference=reference,
    )

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_request_error(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a connection error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    fake_enhancement_requests = fake_repository(init_entries=[enhancement_request])

    service = RobotService(
        fake_uow(enhancement_requests=fake_enhancement_requests),
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotUnreachableError):
        await service.request_enhancement_from_robot(
            robot_url=ROBOT_URL,
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_503_response(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a robot that is unavailable
    httpx_mock.add_response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    fake_enhancement_requests = fake_repository(init_entries=[enhancement_request])

    service = RobotService(
        fake_uow(enhancement_requests=fake_enhancement_requests),
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotUnreachableError):
        await service.request_enhancement_from_robot(
            robot_url=ROBOT_URL,
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.mark.asyncio
async def test_request_enhancement_from_robot_400_response(
    fake_uow, fake_repository, httpx_mock
):
    # Mock a robot that is unavailable
    httpx_mock.add_response(
        status_code=status.HTTP_400_BAD_REQUEST, json={"message": "bad request"}
    )

    reference = Reference(id=uuid.uuid4(), visibility=Visibility.RESTRICTED)
    enhancement_request = EnhancementRequest(
        id=uuid.uuid4(),
        reference_id=reference.id,
        robot_id=ROBOT_ID,
        enhancement_parameters={},
    )

    fake_enhancement_requests = fake_repository(init_entries=[enhancement_request])

    service = RobotService(
        fake_uow(enhancement_requests=fake_enhancement_requests),
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    with pytest.raises(RobotEnhancementError):
        await service.request_enhancement_from_robot(
            robot_url=ROBOT_URL,
            enhancement_request=enhancement_request,
            reference=reference,
        )


@pytest.fixture
def azure_file_mocks(monkeypatch):
    mock_file = Mock()
    mock_file.to_sql.return_value = "mock_sql_value"
    mock_file.to_signed_url.return_value = "https://example.com/signed-url"

    # List to track calls
    upload_calls = []
    file_calls = []

    async def mock_upload(file, path, filename):
        upload_calls.append({"file": file, "path": path, "filename": filename})
        return mock_file

    def mock_file_creation(path, filename):
        file_calls.append({"path": path, "filename": filename})
        return mock_file

    monkeypatch.setattr(
        "app.domain.robots.service.upload_file_to_azure_blob_storage", mock_upload
    )
    monkeypatch.setattr(
        "app.persistence.blob.models.BlobStorageFile", mock_file_creation
    )

    return {
        "mock_file": mock_file,
        "upload_calls": upload_calls,
        "file_calls": file_calls,
    }


@pytest.mark.asyncio
async def test_collect_and_dispatch_references_for_batch_enhancement_happy_path(
    fake_uow, fake_repository, httpx_mock, azure_file_mocks
):
    # Setup
    batch_enhancement_request_id = uuid.uuid4()
    reference_ids = [uuid.uuid4(), uuid.uuid4()]

    batch_enhancement_request = BatchEnhancementRequest(
        id=batch_enhancement_request_id,
        robot_id=ROBOT_ID,
        reference_ids=reference_ids,
        enhancement_parameters={},
    )

    # Mock references
    references = [
        Reference(
            id=ref_id,
            visibility=Visibility.RESTRICTED,
            enhancements=[],
            identifiers=[],
        )
        for ref_id in reference_ids
    ]

    # Mock reference service
    reference_service = Mock()
    reference_service.get_hydrated_references = AsyncMock(return_value=references)

    # Setup fake repository
    fake_batch_requests = fake_repository(init_entries=[batch_enhancement_request])

    # Set up UOW
    fake_unit_of_work = fake_uow(batch_enhancement_requests=fake_batch_requests)

    # Set up robot service
    service = RobotService(
        fake_unit_of_work,
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    httpx_mock.add_response(
        method="POST",
        url=str(ROBOT_URL),
        status_code=status.HTTP_202_ACCEPTED,
    )

    await service.collect_and_dispatch_references_for_batch_enhancement(
        batch_enhancement_request=batch_enhancement_request,
        reference_service=reference_service,
    )

    # Verify
    reference_service.get_hydrated_references.assert_called_once_with(
        reference_ids,
        enhancement_types=[],
        external_identifier_types=[],
    )

    batch_request = await fake_batch_requests.get_by_pk(batch_enhancement_request_id)
    assert batch_request.reference_data_file == "mock_sql_value"
    assert batch_request.request_status == BatchEnhancementRequestStatus.ACCEPTED
    assert batch_request.id == batch_enhancement_request_id
    assert set(batch_request.reference_ids) == set(reference_ids)
    assert batch_request.n_references == len(references)

    upload_calls = azure_file_mocks["upload_calls"]
    file_calls = azure_file_mocks["file_calls"]

    # Verify upload call arguments
    assert len(upload_calls) == 1
    assert upload_calls[0]["path"] == "batch_enhancement_request_reference_data"
    assert upload_calls[0]["filename"] == f"{batch_enhancement_request_id}.jsonl"
    assert isinstance(upload_calls[0]["file"], bytes)

    assert len(file_calls) == 1
    assert file_calls[0]["path"] == "batch_enhancement_result"
    assert file_calls[0]["filename"] == f"{batch_enhancement_request_id}.jsonl"


@pytest.mark.asyncio
async def test_collect_and_dispatch_references_for_batch_enhancement_robot_unreachable(
    fake_uow,
    fake_repository,
    httpx_mock,
    azure_file_mocks,  # noqa: ARG001
):
    # Setup
    batch_enhancement_request_id = uuid.uuid4()
    reference_ids = [uuid.uuid4(), uuid.uuid4()]

    batch_enhancement_request = BatchEnhancementRequest(
        id=batch_enhancement_request_id,
        robot_id=ROBOT_ID,
        reference_ids=reference_ids,
        enhancement_parameters={},
    )

    # Mock references
    references = [
        Reference(
            id=ref_id,
            visibility=Visibility.RESTRICTED,
            enhancements=[],
            identifiers=[],
        )
        for ref_id in reference_ids
    ]

    # Mock reference service
    reference_service = Mock()
    reference_service.get_hydrated_references = AsyncMock(return_value=references)

    # Setup fake repository
    fake_batch_requests = fake_repository(init_entries=[batch_enhancement_request])

    # Set up UOW
    fake_unit_of_work = fake_uow(batch_enhancement_requests=fake_batch_requests)

    # Set up robot service
    service = RobotService(
        fake_unit_of_work,
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    # Simulate robot unreachable error
    httpx_mock.add_exception(httpx.ConnectError(message="All connections refused"))

    await service.collect_and_dispatch_references_for_batch_enhancement(
        batch_enhancement_request=batch_enhancement_request,
        reference_service=reference_service,
    )

    batch_request = await fake_batch_requests.get_by_pk(batch_enhancement_request_id)
    assert batch_request.request_status == BatchEnhancementRequestStatus.FAILED


@pytest.mark.asyncio
async def test_collect_and_dispatch_references_for_batch_enhancement_robot_rejected(
    fake_uow,
    fake_repository,
    httpx_mock,
    azure_file_mocks,  # noqa: ARG001
):
    # Setup
    batch_enhancement_request_id = uuid.uuid4()
    reference_ids = [uuid.uuid4(), uuid.uuid4()]

    batch_enhancement_request = BatchEnhancementRequest(
        id=batch_enhancement_request_id,
        robot_id=ROBOT_ID,
        reference_ids=reference_ids,
        enhancement_parameters={},
    )

    # Mock references
    references = [
        Reference(
            id=ref_id,
            visibility=Visibility.RESTRICTED,
            enhancements=[],
            identifiers=[],
        )
        for ref_id in reference_ids
    ]

    # Mock reference service
    reference_service = Mock()
    reference_service.get_hydrated_references = AsyncMock(return_value=references)

    # Setup fake repository
    fake_batch_requests = fake_repository(init_entries=[batch_enhancement_request])

    # Set up UOW
    fake_unit_of_work = fake_uow(batch_enhancement_requests=fake_batch_requests)

    # Set up robot service
    service = RobotService(
        fake_unit_of_work,
        robots=Robots(known_robots=KNOWN_ROBOTS),
    )

    # Simulate robot rejection with a 400 response
    httpx_mock.add_response(
        method="POST",
        url=str(ROBOT_URL),
        status_code=status.HTTP_400_BAD_REQUEST,
        json={"message": "Invalid request"},
    )

    await service.collect_and_dispatch_references_for_batch_enhancement(
        batch_enhancement_request=batch_enhancement_request,
        reference_service=reference_service,
    )

    batch_request = await fake_batch_requests.get_by_pk(batch_enhancement_request_id)
    assert batch_request.request_status == BatchEnhancementRequestStatus.REJECTED
    assert "Invalid request" in batch_request.error
