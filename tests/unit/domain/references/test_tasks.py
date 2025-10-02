"""Unit tests for the tasks module in the references domain."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.references.models.models import (
    EnhancementRequest,
    PendingEnhancementStatus,
    RobotAutomationPercolationResult,
    RobotEnhancementBatch,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.tasks import (
    detect_and_dispatch_robot_automations,
    validate_and_import_robot_enhancement_batch_result,
)


async def test_robot_automations(monkeypatch, fake_uow, fake_repository):
    """
    Test the detect_and_dispatch_robot_automations task distributor.
    Only tests function signatures, functionality itself is tested in the service layer.
    """
    in_reference_ids = {uuid.uuid4(), uuid.uuid4()}
    in_enhancement_ids = {uuid.uuid4(), uuid.uuid4()}
    robot_id = uuid.uuid4()

    expected_request = EnhancementRequest(
        reference_ids=in_reference_ids,
        robot_id=robot_id,
        id=uuid.uuid4(),
        status="RECEIVED",
        source="test_source",
    )
    mock_register_request = AsyncMock(return_value=expected_request)
    monkeypatch.setattr(
        ReferenceService,
        "register_reference_enhancement_request",
        mock_register_request,
    )

    mock_detect_robot_automations = AsyncMock(
        return_value=[
            RobotAutomationPercolationResult(
                robot_id=robot_id, reference_ids=in_reference_ids
            )
        ]
    )
    monkeypatch.setattr(
        ReferenceService,
        "detect_robot_automations",
        mock_detect_robot_automations,
    )

    requests = await detect_and_dispatch_robot_automations(
        reference_service=ReferenceService(
            ReferenceAntiCorruptionService(fake_repository), fake_uow(), fake_uow()
        ),
        reference_ids=in_reference_ids,
        enhancement_ids=in_enhancement_ids,
        source_str="test_source",
    )
    assert len(requests) == 1
    assert requests[0] == expected_request

    mock_register_request.assert_awaited_once()
    assert (
        set(mock_register_request.call_args[1]["enhancement_request"].reference_ids)
        == in_reference_ids
    )
    assert (
        mock_register_request.call_args[1]["enhancement_request"].robot_id == robot_id
    )
    mock_detect_robot_automations.assert_awaited_once_with(
        reference_ids=in_reference_ids, enhancement_ids=in_enhancement_ids
    )


@pytest.fixture
def mock_sql_uow_cm(monkeypatch):
    cm = AsyncMock()
    cm.__aenter__.return_value = AsyncMock()
    cm.__aexit__.return_value = AsyncMock()
    monkeypatch.setattr(
        "app.domain.references.tasks.get_sql_unit_of_work",
        lambda: cm,
    )
    return cm


@pytest.fixture
def mock_es_uow_cm(monkeypatch):
    cm = AsyncMock()
    cm.__aenter__.return_value = AsyncMock()
    cm.__aexit__.return_value = AsyncMock()
    monkeypatch.setattr(
        "app.domain.references.tasks.get_es_unit_of_work",
        lambda: cm,
    )
    return cm


@pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
async def test_validate_and_import_robot_enhancement_batch_result(monkeypatch):
    """Test the task successfully validates and imports a robot enhancement batch."""

    robot_enhancement_batch_id = uuid.uuid4()
    robot_id = uuid.uuid4()
    imported_enhancement_ids = {uuid.uuid4(), uuid.uuid4()}
    successful_pending_enhancement_ids = {uuid.uuid4(), uuid.uuid4()}
    failed_pending_enhancement_ids = {uuid.uuid4()}

    mock_reference_service = AsyncMock()
    mock_reference_service.get_robot_enhancement_batch.return_value = (
        RobotEnhancementBatch(
            id=robot_enhancement_batch_id,
            robot_id=robot_id,
            pending_enhancements=[],
        )
    )
    result = (
        imported_enhancement_ids,
        successful_pending_enhancement_ids,
        failed_pending_enhancement_ids,
    )
    validate_method = (
        mock_reference_service.validate_and_import_robot_enhancement_batch_result
    )
    validate_method.return_value = result

    mock_detect_and_dispatch = AsyncMock(return_value=[])

    monkeypatch.setattr(
        "app.domain.references.tasks.get_blob_repository",
        AsyncMock(return_value=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.get_reference_service",
        AsyncMock(return_value=mock_reference_service),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.detect_and_dispatch_robot_automations",
        mock_detect_and_dispatch,
    )

    await validate_and_import_robot_enhancement_batch_result(robot_enhancement_batch_id)

    mock_reference_service.get_robot_enhancement_batch.assert_awaited_once_with(
        robot_enhancement_batch_id, preload=["pending_enhancements"]
    )

    validate_method.assert_awaited_once()

    mock_detect_and_dispatch.assert_awaited_once()
    call_kwargs = mock_detect_and_dispatch.call_args.kwargs
    assert call_kwargs["enhancement_ids"] == imported_enhancement_ids
    expected_source = f"RobotEnhancementBatch:{robot_enhancement_batch_id}"
    assert call_kwargs["source_str"] == expected_source
    assert call_kwargs["skip_robot_id"] == robot_id

    status_calls = (
        mock_reference_service.update_pending_enhancements_status.call_args_list
    )

    assert len(status_calls) == 3

    failed_call = status_calls[0]
    assert failed_call[1]["pending_enhancement_ids"] == list(
        failed_pending_enhancement_ids
    )
    assert failed_call[1]["status"] == PendingEnhancementStatus.FAILED

    indexing_call = status_calls[1]
    assert indexing_call[1]["pending_enhancement_ids"] == list(
        successful_pending_enhancement_ids
    )
    assert indexing_call[1]["status"] == PendingEnhancementStatus.INDEXING

    completed_call = status_calls[2]
    assert completed_call[1]["pending_enhancement_ids"] == list(
        successful_pending_enhancement_ids
    )
    assert completed_call[1]["status"] == PendingEnhancementStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
async def test_validate_and_import_robot_enhancement_batch_result_handles_exceptions(
    monkeypatch,
):
    """
    Test that the task properly handles and propagates exceptions.

    This test verifies that when validation fails, the batch is marked as failed
    and the error is properly recorded - the key error handling behavior.
    """
    robot_enhancement_batch_id = uuid.uuid4()
    error_message = "Validation failed"

    mock_reference_service = AsyncMock()
    mock_reference_service.get_robot_enhancement_batch.return_value = (
        RobotEnhancementBatch(
            id=robot_enhancement_batch_id,
            robot_id=uuid.uuid4(),
            pending_enhancements=[],
        )
    )
    # Simulate the validation failing
    validate_method = (
        mock_reference_service.validate_and_import_robot_enhancement_batch_result
    )
    validate_method.side_effect = Exception(error_message)

    monkeypatch.setattr(
        "app.domain.references.tasks.get_blob_repository",
        AsyncMock(return_value=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.get_reference_service",
        AsyncMock(return_value=mock_reference_service),
    )

    await validate_and_import_robot_enhancement_batch_result(robot_enhancement_batch_id)

    validate_method.assert_awaited_once()

    mark_failed_method = mock_reference_service.mark_robot_enhancement_batch_failed
    mark_failed_method.assert_awaited_once_with(
        robot_enhancement_batch_id, error_message
    )


@pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
@pytest.mark.asyncio
async def test_validate_and_import_robot_enhancement_batch_result_indexing_failure(
    monkeypatch,
):
    """Test that indexing failures are properly handled without failing the batch."""
    robot_enhancement_batch_id = uuid.uuid4()

    mock_reference_service = AsyncMock()

    mock_batch = AsyncMock()
    mock_batch.id = robot_enhancement_batch_id
    mock_batch.robot_id = uuid.uuid4()
    mock_batch.pending_enhancements = [AsyncMock(reference_id=uuid.uuid4())]
    mock_reference_service.get_robot_enhancement_batch.return_value = mock_batch

    validate_method = (
        mock_reference_service.validate_and_import_robot_enhancement_batch_result
    )
    validate_method.return_value = (
        {uuid.uuid4()},  # imported_enhancement_ids
        {uuid.uuid4()},  # successful_pending_enhancement_ids
        set(),  # failed_pending_enhancement_ids
    )

    mock_reference_service.index_references.side_effect = Exception("Indexing failed")

    monkeypatch.setattr(
        "app.domain.references.tasks.get_blob_repository",
        AsyncMock(return_value=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.get_reference_service",
        AsyncMock(return_value=mock_reference_service),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.detect_and_dispatch_robot_automations",
        AsyncMock(return_value=[]),
    )

    await validate_and_import_robot_enhancement_batch_result(robot_enhancement_batch_id)

    mock_reference_service.index_references.assert_awaited_once()
    mock_reference_service.mark_robot_enhancement_batch_failed.assert_not_called()

    status_calls = (
        mock_reference_service.update_pending_enhancements_status.call_args_list
    )
    assert len(status_calls) == 3

    failed_call = status_calls[0]
    assert failed_call[1]["pending_enhancement_ids"] == []
    assert failed_call[1]["status"] == PendingEnhancementStatus.FAILED

    indexing_call = status_calls[1]
    assert len(indexing_call[1]["pending_enhancement_ids"]) == 1
    assert indexing_call[1]["status"] == PendingEnhancementStatus.INDEXING

    indexing_failed_call = status_calls[2]
    assert len(indexing_failed_call[1]["pending_enhancement_ids"]) == 1
    assert indexing_failed_call[1]["status"] == PendingEnhancementStatus.INDEXING_FAILED
