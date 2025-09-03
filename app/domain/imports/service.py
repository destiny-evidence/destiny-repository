"""The service for interacting with and managing imports."""

import httpx
from asyncpg.exceptions import DeadlockDetectedError  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import UUID4
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import SQLIntegrityError
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRecord,
    ImportRecordStatus,
    ImportResult,
    ImportResultStatus,
)
from app.domain.imports.services.anti_corruption_service import (
    ImportAntiCorruptionService,
)
from app.domain.references.service import ReferenceService
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class ImportService(GenericService[ImportAntiCorruptionService]):
    """The service which manages our imports and their processing."""

    def __init__(
        self,
        anti_corruption_service: ImportAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def _get_import_record(self, import_record_id: UUID4) -> ImportRecord:
        """Get a single import by id."""
        return await self.sql_uow.imports.get_by_pk(import_record_id)

    @sql_unit_of_work
    async def get_import_record(self, import_record_id: UUID4) -> ImportRecord:
        """Get a single import by id."""
        return await self._get_import_record(import_record_id)

    @sql_unit_of_work
    async def get_import_record_with_batches(self, pk: UUID4) -> ImportRecord:
        """Get a single import, eager loading its batches."""
        return await self.sql_uow.imports.get_by_pk(pk, preload=["batches"])

    @sql_unit_of_work
    async def get_import_batch(self, import_batch_id: UUID4) -> ImportBatch:
        """Get a single import batch by id."""
        return await self.sql_uow.batches.get_by_pk(import_batch_id)

    @sql_unit_of_work
    async def get_import_result(self, import_result_id: UUID4) -> ImportResult:
        """Get a single import result by id."""
        return await self.sql_uow.results.get_by_pk(import_result_id)

    @sql_unit_of_work
    async def get_imported_references_from_batch(
        self, import_batch_id: UUID4
    ) -> set[UUID4]:
        """Get all imported references from a batch."""
        results = await self.sql_uow.results.get_by_filter(
            import_batch_id=import_batch_id,
        )
        return {
            result.reference_id
            for result in results
            if result.reference_id
            and result.status
            in (ImportResultStatus.COMPLETED, ImportResultStatus.PARTIALLY_FAILED)
        }

    @sql_unit_of_work
    async def get_import_batch_with_results(
        self, import_batch_id: UUID4
    ) -> ImportBatch:
        """Get a single import batch with preloaded results."""
        return await self.sql_uow.batches.get_by_pk(
            import_batch_id, preload=["import_results"]
        )

    @sql_unit_of_work
    async def register_import(self, import_record: ImportRecord) -> ImportRecord:
        """Register an import, persisting it to the database."""
        return await self.sql_uow.imports.add(import_record)

    @sql_unit_of_work
    async def register_batch(self, batch: ImportBatch) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        # Errors if the import record does not exist
        await self._get_import_record(batch.import_record_id)
        return await self.sql_uow.batches.add(batch)

    @sql_unit_of_work
    async def register_result(self, result: ImportResult) -> ImportResult:
        """Register an import result, persisting it to the database."""
        return await self.sql_uow.results.add(result)

    async def _update_import_batch_status(
        self, import_batch_id: UUID4, status: ImportBatchStatus
    ) -> ImportBatch:
        """Update the status of an import batch."""
        return await self.sql_uow.batches.update_by_pk(import_batch_id, status=status)

    @sql_unit_of_work
    async def update_import_batch_status(
        self, import_batch_id: UUID4, status: ImportBatchStatus
    ) -> ImportBatch:
        """Update the status of an import batch."""
        return await self._update_import_batch_status(import_batch_id, status=status)

    @sql_unit_of_work
    async def update_import_result_status(
        self, import_result_id: UUID4, status: ImportResultStatus
    ) -> ImportResult:
        """Update the status of an import result."""
        return await self.sql_uow.results.update_by_pk(import_result_id, status=status)

    async def process_batch(self, import_batch: ImportBatch) -> ImportBatch:
        """Process an import batch."""
        await self.update_import_batch_status(
            import_batch.id, ImportBatchStatus.STARTED
        )

        async with (
            httpx.AsyncClient() as client,
        ):
            HTTPXClientInstrumentor().instrument_client(client)
            async with client.stream("GET", str(import_batch.storage_url)) as response:
                response.raise_for_status()
                entry_ref = 1
                async for line in response.aiter_lines():
                    if line.strip():
                        import_result = await self.register_result(
                            ImportResult(
                                import_batch_id=import_batch.id,
                                status=ImportResultStatus.CREATED,
                                line_content=line,
                                line_number=entry_ref,
                            )
                        )
                        await queue_task_with_trace(
                            "app.domain.imports.tasks.process_import_result",
                            import_result.id,
                        )
                    entry_ref += 1

        return import_batch

    @tracer.start_as_current_span("Import reference")
    async def process_import_result(
        self, import_result: ImportResult, reference_service: ReferenceService
    ) -> ImportResult:
        """Process an import result."""
        trace_attribute(Attributes.FILE_LINE_NO, import_result.line_number)
        reference_result = await reference_service.ingest_reference(
            import_result.line_content, import_result.line_number
        )

        if not reference_result.reference:
            # Reference was not created
            await self.sql_uow.results.update_by_pk(
                import_result.id,
                failure_details=reference_result.error_str,
                status=ImportResultStatus.FAILED,
            )
        elif reference_result.errors:
            # Reference was created, but errors occurred
            await self.sql_uow.results.update_by_pk(
                import_result.id,
                status=ImportResultStatus.PARTIALLY_FAILED,
                reference_id=reference_result.reference_id,
                failure_details=reference_result.error_str,
            )
        else:
            await self.sql_uow.results.update_by_pk(
                import_result.id,
                status=ImportResultStatus.COMPLETED,
                reference_id=reference_result.reference_id,
            )

        return import_result

    @sql_unit_of_work
    async def add_batch_result(
        self,
        import_result: ImportResult,
    ) -> ImportResult:
        """Persist an import result to the database."""
        db_import_result = ImportResult(**import_result.model_dump())
        return await self.sql_uow.results.add(db_import_result)

    @sql_unit_of_work
    async def get_import_results(
        self,
        import_batch_id: UUID4,
        result_status: ImportResultStatus | None = None,
    ) -> list[ImportResult]:
        """Get a list of results for an import batch."""
        return await self.sql_uow.results.get_by_filter(
            import_batch_id=import_batch_id,
            status=result_status,
        )

    @sql_unit_of_work
    async def finalise_record(self, import_record_id: UUID4) -> None:
        """Finalise an import record."""
        await self.sql_uow.imports.update_by_pk(
            import_record_id, status=ImportRecordStatus.COMPLETED
        )
