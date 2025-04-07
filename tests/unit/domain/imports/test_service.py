"""Unit tests for the ImportService class."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.imports.models.models import ImportResult, ImportResultStatus
from app.domain.imports.service import ImportService
from app.domain.references.models.models import Reference, ReferenceCreateResult

REF_ID = uuid.uuid4()
RESULT_ID = uuid.uuid4()
BATCH_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_import_reference_happy_path(fake_repository, fake_uow):
    repo_results = fake_repository()
    uow = fake_uow(results=repo_results)
    service = ImportService(uow)

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        reference=Reference(id=REF_ID)
    )

    await service.import_reference(BATCH_ID, "nonsense", fake_reference_service, 1)

    import_result = next(iter(repo_results.repository.values()))

    assert import_result.reference_id == REF_ID
    assert import_result.status == ImportResultStatus.COMPLETED


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
