"""Unit tests for the ImportService class."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.imports.models.models import (
    ImportResult,
    ImportResultStatus,
)
from app.domain.imports.service import ImportService
from app.domain.references.models.models import Reference, ReferenceCreateResult
from app.persistence.uow import AsyncUnitOfWorkBase

REF_ID = uuid.uuid4()
RESULT_ID = uuid.uuid4()
BATCH_ID = uuid.uuid4()


class FakeUnitOfWork(AsyncUnitOfWorkBase):
    def __init__(self, results):
        self.results = results
        self.committed = False
        super().__init__()

    async def __aenter__(self):
        self._is_active = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self._is_active = False

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


class FakeRepository:
    def __init__(self):
        self.repository = {}

    async def add(self, record):
        self.repository[record.id] = record
        return record

    async def get_by_pk(self, pk):
        self.repository.get(pk)

    async def update_by_pk(self, pk, **kwargs: object):
        self.repository[pk] = kwargs.items()

    async def delete_by_pk(self, pk):
        self.repository.pop(pk)


@pytest.mark.asyncio
async def test_import_reference_happy_path():
    fake_results_repo = FakeRepository()
    fake_uow = FakeUnitOfWork(fake_results_repo)
    service = ImportService(fake_uow)

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        reference=Reference(id=REF_ID)
    )

    expected_result = {
        "status": ImportResultStatus.COMPLETED,
        "reference_id": REF_ID,
    }.items()

    async with fake_uow:
        await service.import_reference(BATCH_ID, "nonsense", fake_reference_service, 1)

    assert len(fake_results_repo.repository) == 1
    assert next(iter(fake_results_repo.repository.values())) == expected_result


@pytest.mark.asyncio
async def test_import_reference_reference_not_created():
    fake_uow = AsyncMock()
    service = ImportService(fake_uow)
    result = ImportResult(id=RESULT_ID, import_batch_id=BATCH_ID)
    fake_uow.results.add.return_value = result

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        errors=["it bronked"]
    )
    await service.import_reference(BATCH_ID, "nonsense", fake_reference_service, 1)

    fake_uow.results.update_by_pk.assert_called_with(
        result.id, failure_details="it bronked", status=ImportResultStatus.FAILED
    )
