"""Unit tests for the tasks module in the references domain."""

from unittest.mock import AsyncMock
from uuid import uuid7

import pytest

from app.core.exceptions import SQLIntegrityError
from app.domain.references.models.models import (
    DuplicateDetermination,
    EnhancementRequest,
    PendingEnhancementStatus,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceWithChangeset,
    RobotAutomationPercolationResult,
    RobotEnhancementBatch,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.enhancement_service import ProcessedResults
from app.domain.references.tasks import (
    process_reference_duplicate_decision,
    validate_and_import_robot_enhancement_batch_result,
)


async def test_robot_automations(monkeypatch, fake_uow, fake_repository):
    """
    Test the detect_and_dispatch_robot_automations task distributor.
    Only tests function signatures, functionality itself is tested in the service layer.
    """
    reference = ReferenceWithChangeset(changeset=Reference())
    in_enhancement_ids = {uuid7(), uuid7()}
    robot_id = uuid7()

    expected_request = EnhancementRequest(
        reference_ids=[reference.id],
        robot_id=robot_id,
        id=uuid7(),
        status="RECEIVED",
        source="test_source",
    )
    mock_create_pending_enhancements = AsyncMock(return_value=expected_request)
    monkeypatch.setattr(
        ReferenceService,
        "_create_pending_enhancements",
        mock_create_pending_enhancements,
    )

    mock_detect_robot_automations = AsyncMock(
        return_value=[
            RobotAutomationPercolationResult(
                robot_id=robot_id, reference_ids=[reference.id]
            )
        ]
    )
    monkeypatch.setattr(
        ReferenceService,
        "_detect_robot_automations",
        mock_detect_robot_automations,
    )

    await ReferenceService(
        ReferenceAntiCorruptionService(fake_repository), fake_uow(), fake_uow()
    ).detect_and_dispatch_robot_automations(
        reference=reference,
        enhancement_ids=in_enhancement_ids,
        source_str="test_source",
    )

    mock_create_pending_enhancements.assert_awaited_once()
    assert set(mock_create_pending_enhancements.call_args[1]["reference_ids"]) == {
        reference.id
    }
    assert mock_create_pending_enhancements.call_args[1]["robot_id"] == robot_id
    assert mock_create_pending_enhancements.call_args[1]["source"] == "test_source"
    mock_detect_robot_automations.assert_awaited_once_with(
        reference=reference, enhancement_ids=in_enhancement_ids
    )


@pytest.fixture
def mock_sql_uow_cm(monkeypatch):
    cm = AsyncMock()
    cm.__aenter__.return_value = AsyncMock()
    cm.__aexit__.return_value = None  # Don't suppress exceptions
    monkeypatch.setattr(
        "app.domain.references.tasks.get_sql_unit_of_work",
        lambda: cm,
    )
    return cm


@pytest.fixture
def mock_es_uow_cm(monkeypatch):
    cm = AsyncMock()
    cm.__aenter__.return_value = AsyncMock()
    cm.__aexit__.return_value = None  # Don't suppress exceptions
    monkeypatch.setattr(
        "app.domain.references.tasks.get_es_unit_of_work",
        lambda: cm,
    )
    return cm


@pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
async def test_validate_and_import_robot_enhancement_batch_result(monkeypatch):
    """Test the task successfully validates and imports a robot enhancement batch."""

    robot_enhancement_batch_id = uuid7()
    robot_id = uuid7()
    imported_enhancement_ids = {uuid7(), uuid7()}
    successful_pending_enhancement_ids = {uuid7(), uuid7()}
    failed_pending_enhancement_ids = {uuid7()}
    discarded_pending_enhancement_ids = {uuid7()}

    mock_reference_service = AsyncMock()
    mock_reference_service.get_robot_enhancement_batch.return_value = (
        RobotEnhancementBatch(
            id=robot_enhancement_batch_id,
            robot_id=robot_id,
            pending_enhancements=[],
        )
    )
    result = ProcessedResults(
        imported_enhancement_ids,
        successful_pending_enhancement_ids,
        failed_pending_enhancement_ids,
        discarded_pending_enhancement_ids,
    )
    validate_method = (
        mock_reference_service.validate_and_import_robot_enhancement_batch_result
    )
    validate_method.return_value = result

    mock_detect_and_dispatch = (
        mock_reference_service.detect_and_dispatch_robot_automations
    )
    mock_detect_and_dispatch.return_value = []

    monkeypatch.setattr(
        "app.domain.references.tasks.get_blob_repository",
        AsyncMock(return_value=AsyncMock()),
    )
    monkeypatch.setattr(
        "app.domain.references.tasks.get_reference_service",
        AsyncMock(return_value=mock_reference_service),
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

    assert len(status_calls) == 4

    failed_call = status_calls[0]
    assert failed_call[1]["pending_enhancement_ids"] == list(
        failed_pending_enhancement_ids
    )
    assert failed_call[1]["status"] == PendingEnhancementStatus.FAILED

    discarded_call = status_calls[1]
    assert discarded_call[1]["pending_enhancement_ids"] == list(
        discarded_pending_enhancement_ids
    )
    assert discarded_call[1]["status"] == PendingEnhancementStatus.DISCARDED

    indexing_call = status_calls[2]
    assert indexing_call[1]["pending_enhancement_ids"] == list(
        successful_pending_enhancement_ids
    )
    assert indexing_call[1]["status"] == PendingEnhancementStatus.INDEXING

    completed_call = status_calls[3]
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
    robot_enhancement_batch_id = uuid7()
    error_message = "Validation failed"

    mock_reference_service = AsyncMock()
    mock_reference_service.get_robot_enhancement_batch.return_value = (
        RobotEnhancementBatch(
            id=robot_enhancement_batch_id,
            robot_id=uuid7(),
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
    robot_enhancement_batch_id = uuid7()

    mock_reference_service = AsyncMock()

    mock_batch = AsyncMock()
    mock_batch.id = robot_enhancement_batch_id
    mock_batch.robot_id = uuid7()
    mock_batch.pending_enhancements = [AsyncMock(reference_id=uuid7())]
    mock_reference_service.get_robot_enhancement_batch.return_value = mock_batch

    validate_method = (
        mock_reference_service.validate_and_import_robot_enhancement_batch_result
    )
    validate_method.return_value = ProcessedResults(
        {uuid7()},  # imported_enhancement_ids
        {uuid7()},  # successful_pending_enhancement_ids
        set(),  # failed_pending_enhancement_ids
        set(),  # discarded_pending_enhancement_ids
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
        "app.domain.references.service.ReferenceService.detect_and_dispatch_robot_automations",
        AsyncMock(return_value=[]),
    )

    await validate_and_import_robot_enhancement_batch_result(robot_enhancement_batch_id)

    mock_reference_service.index_references.assert_awaited_once()
    mock_reference_service.mark_robot_enhancement_batch_failed.assert_not_called()

    status_calls = (
        mock_reference_service.update_pending_enhancements_status.call_args_list
    )
    assert len(status_calls) == 4

    failed_call = status_calls[0]
    assert failed_call[1]["pending_enhancement_ids"] == []
    assert failed_call[1]["status"] == PendingEnhancementStatus.FAILED

    indexing_call = status_calls[2]
    assert len(indexing_call[1]["pending_enhancement_ids"]) == 1
    assert indexing_call[1]["status"] == PendingEnhancementStatus.INDEXING

    indexing_failed_call = status_calls[3]
    assert len(indexing_failed_call[1]["pending_enhancement_ids"]) == 1
    assert indexing_failed_call[1]["status"] == PendingEnhancementStatus.INDEXING_FAILED


class TestProcessReferenceDuplicateDecisionRaceCondition:
    """Tests for race condition handling in process_reference_duplicate_decision."""

    @pytest.fixture
    def decision_id(self):
        return uuid7()

    @pytest.fixture
    def reference_id(self):
        return uuid7()

    @pytest.fixture
    def mock_decision_pending(self, decision_id, reference_id):
        return ReferenceDuplicateDecision(
            id=decision_id,
            reference_id=reference_id,
            duplicate_determination=DuplicateDetermination.PENDING,
            active_decision=False,  # PENDING decisions can't be active
        )

    @pytest.fixture
    def mock_decision_canonical(self, decision_id, reference_id):
        return ReferenceDuplicateDecision(
            id=decision_id,
            reference_id=reference_id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
            active_decision=True,
        )

    @pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
    async def test_race_condition_handled_gracefully(
        self,
        monkeypatch,
        mock_sql_uow_cm,
        decision_id,
        mock_decision_pending,
        mock_decision_canonical,
    ):
        """
        Test that when SQLIntegrityError occurs and another worker already
        processed the decision, we skip gracefully without raising.
        """
        mock_reference_service = AsyncMock()
        # First call returns PENDING, second call (after rollback) returns CANONICAL
        mock_reference_service.get_reference_duplicate_decision.side_effect = [
            mock_decision_pending,
            mock_decision_canonical,
        ]
        mock_reference_service.process_reference_duplicate_decision.side_effect = (
            SQLIntegrityError(
                detail="Integrity error",
                lookup_model="ReferenceDuplicateDecision",
                collision="unique constraint violation",
            )
        )

        monkeypatch.setattr(
            "app.domain.references.tasks.get_blob_repository",
            AsyncMock(return_value=AsyncMock()),
        )
        monkeypatch.setattr(
            "app.domain.references.tasks.get_reference_service",
            AsyncMock(return_value=mock_reference_service),
        )

        # Should not raise - race condition handled gracefully
        await process_reference_duplicate_decision(decision_id)

        # Verify rollback was called on the sql_uow
        sql_uow = mock_sql_uow_cm.__aenter__.return_value
        sql_uow.rollback.assert_awaited_once()

        # Verify we fetched the decision twice (initial + re-fetch after error)
        assert mock_reference_service.get_reference_duplicate_decision.await_count == 2

    @pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
    async def test_different_model_collision_reraises(
        self,
        monkeypatch,
        decision_id,
        mock_decision_pending,
    ):
        """
        Test that SQLIntegrityError with a different lookup_model is re-raised.
        """
        mock_reference_service = AsyncMock()
        mock_reference_service.get_reference_duplicate_decision.side_effect = [
            mock_decision_pending
        ]
        mock_reference_service.process_reference_duplicate_decision.side_effect = (
            SQLIntegrityError(
                detail="Integrity error",
                lookup_model="SomeOtherModel",  # Different model - should re-raise
                collision="unique constraint violation",
            )
        )

        monkeypatch.setattr(
            "app.domain.references.tasks.get_blob_repository",
            AsyncMock(return_value=AsyncMock()),
        )
        monkeypatch.setattr(
            "app.domain.references.tasks.get_reference_service",
            AsyncMock(return_value=mock_reference_service),
        )

        with pytest.raises(SQLIntegrityError) as exc_info:
            await process_reference_duplicate_decision(decision_id)

        assert exc_info.value.lookup_model == "SomeOtherModel"
        mock_reference_service.process_reference_duplicate_decision.assert_awaited_once()

    @pytest.mark.usefixtures("mock_sql_uow_cm", "mock_es_uow_cm")
    async def test_still_pending_after_refetch_reraises(
        self,
        monkeypatch,
        mock_sql_uow_cm,
        decision_id,
        mock_decision_pending,
    ):
        """
        Test that when decision is still PENDING after re-fetch, we re-raise
        since it's a different integrity issue (not a race condition).
        """
        mock_reference_service = AsyncMock()
        # Both calls return PENDING - not a race condition, different issue
        mock_reference_service.get_reference_duplicate_decision.side_effect = [
            mock_decision_pending,
            mock_decision_pending,  # Still PENDING after re-fetch
        ]
        mock_reference_service.process_reference_duplicate_decision.side_effect = (
            SQLIntegrityError(
                detail="Integrity error",
                lookup_model="ReferenceDuplicateDecision",
                collision="unique constraint violation",
            )
        )

        monkeypatch.setattr(
            "app.domain.references.tasks.get_blob_repository",
            AsyncMock(return_value=AsyncMock()),
        )
        monkeypatch.setattr(
            "app.domain.references.tasks.get_reference_service",
            AsyncMock(return_value=mock_reference_service),
        )

        with pytest.raises(SQLIntegrityError):
            await process_reference_duplicate_decision(decision_id)

        # Verify rollback was still called
        sql_uow = mock_sql_uow_cm.__aenter__.return_value
        sql_uow.rollback.assert_awaited_once()
