"""Unit tests for the ImportService class."""

import uuid
from unittest.mock import AsyncMock

import destiny_sdk
import httpx
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
from app.domain.imports.services.anti_corruption_service import (
    ImportAntiCorruptionService,
)
from app.domain.references.models.validators import ReferenceCreateResult

RECORD_ID = uuid.uuid4()
REF_ID = uuid.uuid4()
RESULT_ID = uuid.uuid4()
BATCH_ID = uuid.uuid4()


@pytest.fixture
async def import_result():
    return ImportResult(
        id=RESULT_ID,
        import_batch_id=BATCH_ID,
        status=ImportResultStatus.CREATED,
    )


@pytest.mark.asyncio
async def test_register_import(fake_repository, fake_uow):
    repo_imports = fake_repository()
    uow = fake_uow(imports=repo_imports)
    service = ImportService(ImportAntiCorruptionService(), uow)

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
    repo_batches = fake_repository()
    repo_imports = fake_repository(
        init_entries=[fake_import_record(RECORD_ID)], batches=repo_batches
    )
    uow = fake_uow(imports=repo_imports)
    service = ImportService(ImportAntiCorruptionService(), uow)

    batch_to_register = ImportBatch(
        import_record_id=RECORD_ID, storage_url="https://www.totallyrealstorage.com"
    )

    await service.register_batch(batch_to_register)

    import_batch = next(iter(repo_batches.repository.values()))

    assert import_batch.import_record_id == RECORD_ID
    assert import_batch.import_results is None


@pytest.mark.asyncio
async def test_import_reference_happy_path(fake_repository, fake_uow, import_result):
    repo_results = fake_repository([import_result])
    repo_batches = fake_repository(results=repo_results)
    repo = fake_repository(batches=repo_batches)
    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        reference=destiny_sdk.references.ReferenceFileInput(),
    )

    await service.import_reference(
        fake_reference_service, import_result, CollisionStrategy.FAIL, "nonsense", 1
    )

    import_result = repo_results.get_first_record()
    assert import_result.id
    assert import_result.status == ImportResultStatus.COMPLETED


@pytest.mark.asyncio
async def test_import_reference_reference_not_created(
    fake_repository, fake_uow, import_result
):
    repo_results = fake_repository([import_result])
    repo_batches = fake_repository(results=repo_results)
    repo = fake_repository(batches=repo_batches)
    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    import_reference_error = "it bronked"

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        errors=[import_reference_error]
    )

    await service.import_reference(
        fake_reference_service, import_result, CollisionStrategy.FAIL, "nonsense", 1
    )

    import_result = repo_results.get_first_record()

    assert import_result.status == ImportResultStatus.FAILED
    assert import_result.failure_details == import_reference_error


@pytest.mark.asyncio
async def test_import_reference_reference_created_with_errors(
    fake_repository, fake_uow, import_result
):
    repo_results = fake_repository([import_result])
    repo_batches = fake_repository(results=repo_results)
    repo = fake_repository(batches=repo_batches)
    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    import_reference_error = "it's a bit bronked"

    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.return_value = ReferenceCreateResult(
        reference=destiny_sdk.references.ReferenceFileInput(),
        errors=[import_reference_error],
    )

    await service.import_reference(
        fake_reference_service, import_result, CollisionStrategy.FAIL, "nonsense", 1
    )

    import_result = repo_results.get_first_record()
    assert import_result.status == ImportResultStatus.PARTIALLY_FAILED
    assert import_result.failure_details == import_reference_error


@pytest.mark.asyncio
async def test_import_reference_sql_integrity_error(
    fake_repository, fake_uow, import_result
):
    """Test SQLIntegrityError handling in import_reference (should retry)."""
    from app.core.exceptions import SQLIntegrityError

    repo_results = fake_repository([import_result])
    repo_batches = fake_repository(results=repo_results)
    repo = fake_repository(batches=repo_batches)
    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    # Provide all required arguments for SQLIntegrityError
    fake_reference_service = AsyncMock()
    fake_reference_service.ingest_reference.side_effect = SQLIntegrityError(
        detail="Integrity error",
        lookup_model="ImportResult",
        collision="test-collision",
    )

    result, _ = await service.import_reference(
        fake_reference_service, import_result, CollisionStrategy.FAIL, "nonsense", 1
    )

    assert result.status == ImportResultStatus.RETRYING


@pytest.mark.asyncio
async def test_distribute_import_batch_happy_path(monkeypatch, fake_uow):
    """Test distribute_import_batch happy path with multiple lines."""

    # Prepare a fake ImportBatch
    batch_id = uuid.uuid4()
    import_batch = ImportBatch(
        id=batch_id,
        storage_url="https://fake-storage-url.com",
        status=ImportBatchStatus.CREATED,
        import_record_id=uuid.uuid4(),
    )

    # Prepare lines to be returned by the HTTPX stream
    lines = ["ref1", "ref2", "ref3"]

    class FakeResponse:
        def __init__(self, lines):
            self._lines = lines
            self._idx = 0
            self.status_code = 200

        async def aiter_lines(self):
            for line in self._lines:
                yield line

        def raise_for_status(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class FakeStreamContext:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class FakeClient:
        def __init__(self, lines):
            self._lines = lines
            self._transport = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url):
            assert method == "GET"
            assert url == str(import_batch.storage_url)
            response = FakeResponse(self._lines)
            return FakeStreamContext(response)

    monkeypatch.setattr(httpx, "AsyncClient", lambda: FakeClient(lines))

    created_results = []

    async def fake_register_result(result):
        created_results.append(result)
        return result

    queued_tasks = []

    async def fake_queue_task_with_trace(*args):
        queued_tasks.append(args)

    service = ImportService(ImportAntiCorruptionService(), fake_uow())
    monkeypatch.setattr(service, "register_result", fake_register_result)
    monkeypatch.setattr(
        "app.domain.imports.service.queue_task_with_trace", fake_queue_task_with_trace
    )

    await service.distribute_import_batch(import_batch)

    assert len(created_results) == len(lines)
    assert len(queued_tasks) == len(lines)


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
    repo = fake_repository(batches=repo_batches)

    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = ImportAntiCorruptionService().import_batch_to_sdk_summary(batch)

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
    repo = fake_repository(batches=repo_batches)

    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = ImportAntiCorruptionService().import_batch_to_sdk_summary(batch)

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
    repo = fake_repository(batches=repo_batches)

    uow = fake_uow(imports=repo)
    service = ImportService(ImportAntiCorruptionService(), uow)

    batch = await service.get_import_batch_with_results(BATCH_ID)
    summary = ImportAntiCorruptionService().import_batch_to_sdk_summary(batch)

    assert summary.results.get(ImportResultStatus.COMPLETED) == 1
    assert summary.results.get(ImportResultStatus.STARTED) == 1
    assert summary.import_batch_status == ImportBatchStatus.STARTED
