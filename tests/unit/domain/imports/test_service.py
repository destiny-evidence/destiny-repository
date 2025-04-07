"""Unit tests for the ImportService class."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.imports.models.models import (
    ImportBatchCreate,
    ImportBatchStatus,
    ImportRecord,
    ImportRecordCreate,
    ImportRecordStatus,
    ImportResultStatus,
)
from app.domain.imports.service import ImportService
from app.domain.references.models.models import Reference, ReferenceCreateResult

RECORD_ID = uuid.uuid4()
REF_ID = uuid.uuid4()
RESULT_ID = uuid.uuid4()
BATCH_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_register_import(fake_repository, fake_uow):
    repo_imports = fake_repository()
    uow = fake_uow(imports=repo_imports)
    service = ImportService(uow)

    import_to_register = ImportRecordCreate(
        search_string="climate AND health",
        searched_at="2025-02-02T13:29:30Z",
        processor_name="Test Importer",
        processor_version="0.0.1",
        notes="test import",
        expected_reference_count=100,
        source_name="OpenAlex",
    )

    await service.register_import(import_to_register)

    import_record = next(iter(repo_imports.repository.values()))

    assert import_record.status == ImportRecordStatus.CREATED
    assert import_record.search_string == "climate AND health"


@pytest.mark.asyncio
async def test_register_batch(fake_repository, fake_uow):
    fake_import = ImportRecord(
        id=RECORD_ID,
        search_string="climate AND health",
        searched_at="2025-02-02T13:29:30Z",
        processor_name="Test Importer",
        processor_version="0.0.1",
        notes="test import",
        expected_reference_count=100,
        source_name="OpenAlex",
    )

    repo_imports = fake_repository(init_entries=[fake_import])
    repo_batches = fake_repository()
    uow = fake_uow(imports=repo_imports, batches=repo_batches)
    service = ImportService(uow)

    batch_to_register = ImportBatchCreate(
        storage_url="https://www.totallyrealstorage.com"
    )

    await service.register_batch(
        import_record_id=RECORD_ID, batch_create=batch_to_register
    )

    import_batch = next(iter(repo_batches.repository.values()))

    assert import_batch.status == ImportBatchStatus.CREATED
    assert import_batch.import_record_id == RECORD_ID
    assert import_batch.import_results is None


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
async def test_import_reference_reference_not_created(fake_repository, fake_uow):
    repo_results = fake_repository()
    uow = fake_uow(results=repo_results)
    service = ImportService(uow)

    import_reference_error = "it bronked"

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        errors=[import_reference_error]
    )

    await service.import_reference(BATCH_ID, "nonsense", fake_reference_service, 1)

    import_result = next(iter(repo_results.repository.values()))

    assert import_result.status == ImportResultStatus.FAILED
    assert import_result.failure_details == import_reference_error


@pytest.mark.asyncio
async def test_import_reference_reference_created_with_errors(
    fake_repository, fake_uow
):
    repo_results = fake_repository()
    uow = fake_uow(results=repo_results)
    service = ImportService(uow)

    import_reference_error = "it's a bit bronked"

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        reference=Reference(id=REF_ID), errors=[import_reference_error]
    )

    await service.import_reference(BATCH_ID, "nonsense", fake_reference_service, 1)

    import_result = next(iter(repo_results.repository.values()))
    assert import_result.status == ImportResultStatus.PARTIALLY_FAILED
    assert import_result.failure_details == import_reference_error
