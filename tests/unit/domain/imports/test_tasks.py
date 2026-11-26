"""Tests for the import tasks."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest

from app.core.telemetry.taskiq import TaskPriority
from app.domain.imports import tasks
from app.domain.imports.models.models import ImportResultStatus


@pytest.fixture
def import_service(monkeypatch):
    service = AsyncMock()
    service.wait_for_import_result_with_batch.return_value = MagicMock(
        status=ImportResultStatus.CREATED
    )

    @asynccontextmanager
    async def unit_of_work():
        yield AsyncMock()

    monkeypatch.setattr(tasks, "get_sql_unit_of_work", unit_of_work)
    monkeypatch.setattr(tasks, "get_es_unit_of_work", unit_of_work)
    monkeypatch.setattr(tasks, "get_import_service", AsyncMock(return_value=service))
    monkeypatch.setattr(tasks, "get_reference_service", AsyncMock())
    monkeypatch.setattr(tasks, "BlobRepository", MagicMock())
    return service


@pytest.fixture
def queue(monkeypatch):
    queue = AsyncMock()
    monkeypatch.setattr(tasks, "queue_task_with_trace", queue)
    return queue


@pytest.mark.asyncio
async def test_a_retried_import_stays_on_the_low_priority_queue(import_service, queue):
    import_service.import_reference.return_value = (
        MagicMock(status=ImportResultStatus.RETRYING),
        None,
    )

    await tasks.import_reference(uuid7(), "{}", 1, remaining_retries=1)

    assert queue.await_args.args[0] is tasks.import_reference
    assert queue.await_args.kwargs["priority"] == TaskPriority.LOW


@pytest.mark.asyncio
async def test_deduplication_after_an_import_goes_on_the_low_priority_queue(
    import_service, queue
):
    duplicate_decision_id = uuid7()
    import_service.import_reference.return_value = (
        MagicMock(status=ImportResultStatus.COMPLETED),
        duplicate_decision_id,
    )

    await tasks.import_reference(uuid7(), "{}", 1, remaining_retries=1)

    assert queue.await_args.args == (
        tasks.process_reference_duplicate_decision,
        duplicate_decision_id,
    )
    assert queue.await_args.kwargs["priority"] == TaskPriority.LOW
