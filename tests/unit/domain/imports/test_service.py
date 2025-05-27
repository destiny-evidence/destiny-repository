"""Unit tests for the ImportService class."""

import uuid
from unittest.mock import AsyncMock

import destiny_sdk
import pytest

from app.domain.imports.models.models import (
    CollisionStrategy,
    ImportBatch,
    ImportBatchStatus,
    ImportRecord,
    ImportRecordStatus,
    ImportResult,
    ImportResultStatus,
)
from app.domain.imports.service import ImportService
from app.domain.references.models.validators import ReferenceCreateResult

RECORD_ID = uuid.uuid4()
REF_ID = uuid.uuid4()
RESULT_ID = uuid.uuid4()
BATCH_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_register_import(fake_repository, fake_uow):
    repo_imports = fake_repository()
    uow = fake_uow(imports=repo_imports)
    service = ImportService(uow)

    import_to_register = ImportRecord(
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
async def test_register_batch(fake_repository, fake_uow, fake_import_record):
    repo_imports = fake_repository(init_entries=[fake_import_record(RECORD_ID)])
    repo_batches = fake_repository()
    uow = fake_uow(imports=repo_imports, batches=repo_batches)
    service = ImportService(uow)

    batch_to_register = ImportBatch(
        import_record_id=RECORD_ID, storage_url="https://www.totallyrealstorage.com"
    )

    await service.register_batch(batch_to_register)

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
        reference=destiny_sdk.references.ReferenceFileInput(),
    )

    await service.import_reference(
        BATCH_ID, CollisionStrategy.FAIL, "nonsense", fake_reference_service, 1
    )

    import_result = repo_results.get_first_record()
    assert import_result.id
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

    await service.import_reference(
        BATCH_ID, CollisionStrategy.FAIL, "nonsense", fake_reference_service, 1
    )

    import_result = repo_results.get_first_record()

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
        reference=destiny_sdk.references.ReferenceFileInput(),
        errors=[import_reference_error],
    )

    await service.import_reference(
        BATCH_ID, CollisionStrategy.FAIL, "nonsense", fake_reference_service, 1
    )

    import_result = repo_results.get_first_record()
    assert import_result.status == ImportResultStatus.PARTIALLY_FAILED
    assert import_result.failure_details == import_reference_error


@pytest.mark.asyncio
async def test_add_batch_result(fake_repository, fake_uow):
    repo_results = fake_repository()
    uow = fake_uow(results=repo_results)
    service = ImportService(uow)

    import_result_create = ImportResult(
        import_batch_id=BATCH_ID, status=ImportResultStatus.CREATED
    )

    import_result = await service.add_batch_result(import_result_create)

    assert import_result.import_batch_id == BATCH_ID


@pytest.mark.asyncio
async def test_get_import_batch_summary_batch_completed_no_failures(
    fake_repository, fake_uow, fake_import_batch
):
    fake_import_result_completed = ImportResult(
        id=uuid.uuid4(),
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.COMPLETED,
        reference_id=REF_ID,
    )

    fake_completed_batch = fake_import_batch(
        id=BATCH_ID,
        status=ImportBatchStatus.COMPLETED,
        import_results=[fake_import_result_completed],
    )

    repo_batches = fake_repository(init_entries=[fake_completed_batch])

    uow = fake_uow(batches=repo_batches)
    service = ImportService(uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = batch.to_sdk_summary()

    assert summary.results.get(ImportResultStatus.COMPLETED) == 1
    assert summary.results.get(ImportResultStatus.FAILED) == 0
    assert summary.results.get(ImportResultStatus.PARTIALLY_FAILED) == 0
    assert summary.import_batch_status == ImportBatchStatus.COMPLETED


@pytest.mark.asyncio
async def test_get_import_batch_summary_batch_completed_with_failures(
    fake_repository, fake_uow, fake_import_batch
):
    fake_import_result_failed = ImportResult(
        id=uuid.uuid4(),
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.FAILED,
        failure_details="ded",
    )

    fake_import_result_partial_failed = ImportResult(
        id=uuid.uuid4(),
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.PARTIALLY_FAILED,
        reference_id=uuid.uuid4(),
        failure_details="not ded, but close",
    )

    fake_batch = fake_import_batch(
        id=BATCH_ID,
        status=ImportBatchStatus.COMPLETED,
        import_results=[fake_import_result_failed, fake_import_result_partial_failed],
    )

    repo_batches = fake_repository(init_entries=[fake_batch])

    uow = fake_uow(batches=repo_batches)
    service = ImportService(uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = batch.to_sdk_summary()

    assert summary.results.get(ImportResultStatus.FAILED) == 1
    assert summary.results.get(ImportResultStatus.PARTIALLY_FAILED) == 1
    assert summary.failure_details == ["ded", "not ded, but close"]
    assert summary.import_batch_status == ImportBatchStatus.COMPLETED


@pytest.mark.asyncio
async def test_get_import_batch_summary_batch_in_progress(
    fake_repository, fake_uow, fake_import_batch
):
    fake_import_result_failed = ImportResult(
        id=uuid.uuid4(),
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.STARTED,
    )

    fake_import_result_partial_failed = ImportResult(
        id=uuid.uuid4(),
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.COMPLETED,
        reference_id=uuid.uuid4(),
    )

    fake_batch = fake_import_batch(
        id=BATCH_ID,
        status=ImportBatchStatus.STARTED,
        import_results=[fake_import_result_failed, fake_import_result_partial_failed],
    )

    repo_batches = fake_repository(init_entries=[fake_batch])

    uow = fake_uow(batches=repo_batches)
    service = ImportService(uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = batch.to_sdk_summary()

    assert summary.results.get(ImportResultStatus.COMPLETED) == 1
    assert summary.results.get(ImportResultStatus.STARTED) == 1
    assert summary.import_batch_status == ImportBatchStatus.STARTED
