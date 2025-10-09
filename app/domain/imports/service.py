"""The service for interacting with and managing imports."""

import httpx
from asyncpg.exceptions import DeadlockDetectedError  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import UUID7
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.exceptions import SQLIntegrityError
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.imports.models.models import (
    CollisionStrategy,
    ImportBatch,
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
settings = get_settings()


class ImportService(GenericService[ImportAntiCorruptionService]):
    """The service which manages our imports and their processing."""

    def __init__(
        self,
        anti_corruption_service: ImportAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def _get_import_record(self, import_record_id: UUID7) -> ImportRecord:
        """Get a single import by id."""
        return await self.sql_uow.imports.get_by_pk(import_record_id)

    @sql_unit_of_work
    async def get_import_record(self, import_record_id: UUID7) -> ImportRecord:
        """Get a single import by id."""
        return await self._get_import_record(import_record_id)

    @sql_unit_of_work
    async def get_import_record_with_batches(self, pk: UUID7) -> ImportRecord:
        """Get a single import, eager loading its batches."""
        return await self.sql_uow.imports.get_by_pk(
            pk, preload=["batches", "ImportBatch.status"]
        )

    @sql_unit_of_work
    async def get_import_batch(self, import_batch_id: UUID7) -> ImportBatch:
        """Get a single import batch."""
        return await self.sql_uow.imports.batches.get_by_pk(
            import_batch_id, preload=["status"]
        )

    @sql_unit_of_work
    async def get_import_result(
        self,
        import_result_id: UUID7,
    ) -> ImportResult:
        """Get a single import result by id."""
        return await self.sql_uow.imports.batches.results.get_by_pk(import_result_id)

    @sql_unit_of_work
    async def get_import_result_with_batch(
        self,
        import_result_id: UUID7,
    ) -> ImportResult:
        """Get a single import result by id."""
        return await self.sql_uow.imports.batches.results.get_by_pk(
            import_result_id, preload=["import_batch"]
        )

    @sql_unit_of_work
    async def get_imported_references_from_batch(
        self, import_batch_id: UUID7
    ) -> set[UUID7]:
        """Get all imported references from a batch."""
        results = await self.sql_uow.imports.batches.results.get_by_filter(
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
        self, import_batch_id: UUID7
    ) -> ImportBatch:
        """Get a single import batch with preloaded results."""
        return await self.sql_uow.imports.batches.get_by_pk(
            import_batch_id, preload=["import_results", "status"]
        )

    @sql_unit_of_work
    async def register_import(self, import_record: ImportRecord) -> ImportRecord:
        """Register an import, persisting it to the database."""
        return await self.sql_uow.imports.add(import_record)

    @sql_unit_of_work
    async def register_batch(self, batch: ImportBatch) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        batch = await self.sql_uow.imports.batches.add(batch)
        return await self.sql_uow.imports.batches.get_by_pk(
            batch.id, preload=["status"]
        )

    @sql_unit_of_work
    async def register_result(self, result: ImportResult) -> ImportResult:
        """Register an import result, persisting it to the database."""
        return await self.sql_uow.imports.batches.results.add(result)

    @sql_unit_of_work
    async def update_import_result(
        self, import_result_id: UUID7, **kwargs: object
    ) -> ImportResult:
        """Update the status of an import result."""
        return await self.sql_uow.imports.batches.results.update_by_pk(
            import_result_id, **kwargs
        )

    async def import_reference(
        self,
        reference_service: ReferenceService,
        import_result: ImportResult,
        collision_strategy: CollisionStrategy,
        content: str,
        line_number: int,
    ) -> ImportResult:
        """Import a reference and persist it to the database."""
        import_result = await self.update_import_result(
            import_result.id, status=ImportResultStatus.STARTED
        )

        try:
            reference_result = await reference_service.ingest_reference(
                content, line_number, collision_strategy
            )
        except SQLIntegrityError as exc:
            # This handles the case where files loaded in parallel cause a conflict at
            # the persistence layer.
            logger.warning(
                "Integrity error processing batch, likely caused by inconsistent state"
                " being loaded in parallel. Will retry if retries remaining.",
                exc_info=exc,
            )
            return await self.update_import_result(
                import_result.id,
                status=ImportResultStatus.RETRYING,
            )
        except (DBAPIError, DeadlockDetectedError) as exc:
            # This handles deadlocks that can occur when multiple processes try to
            # update the same record at the same time.
            logger.warning(
                "Deadlock while processing batch. Will retry if retries remaining.",
                exc_info=exc,
            )
            return await self.update_import_result(
                import_result.id,
                status=ImportResultStatus.RETRYING,
            )
        except Exception:
            logger.exception("Failed to import reference")
            return await self.update_import_result(
                import_result.id,
                status=ImportResultStatus.FAILED,
                failure_details="Uncaught exception at the repository.",
            )

        if not reference_result:
            if collision_strategy == CollisionStrategy.DISCARD:
                # Reference was discarded
                return await self.update_import_result(
                    import_result.id,
                    status=ImportResultStatus.COMPLETED,
                )
            msg = """
Reference was not created, discarded or failed.
This should not happen.
"""
            raise RuntimeError(msg)

        if not reference_result.reference:
            # Reference was not created
            import_result = await self.update_import_result(
                import_result.id,
                failure_details=reference_result.error_str,
                status=ImportResultStatus.FAILED,
            )
        elif reference_result.errors:
            # Reference was created, but errors occurred
            import_result = await self.update_import_result(
                import_result.id,
                status=ImportResultStatus.PARTIALLY_FAILED,
                reference_id=reference_result.reference_id,
                failure_details=reference_result.error_str,
            )
        else:
            import_result = await self.update_import_result(
                import_result.id,
                status=ImportResultStatus.COMPLETED,
                reference_id=reference_result.reference_id,
            )
        return import_result

    async def distribute_import_batch(self, import_batch: ImportBatch) -> None:
        """Distribute an import batch."""
        async with (
            httpx.AsyncClient() as client,
        ):
            HTTPXClientInstrumentor().instrument_client(client)
            async with client.stream("GET", str(import_batch.storage_url)) as response:
                response.raise_for_status()
                line_number = 1
                async for line in response.aiter_lines():
                    trace_attribute(Attributes.FILE_LINE_NO, line_number)
                    if line := line.strip():
                        import_result = await self.register_result(
                            ImportResult(
                                import_batch_id=import_batch.id,
                                status=ImportResultStatus.CREATED,
                            )
                        )
                        await queue_task_with_trace(
                            ("app.domain.imports.tasks", "import_reference"),
                            import_result.id,
                            line,
                            line_number,
                            settings.import_reference_retry_count,
                        )
                        line_number += 1

    @sql_unit_of_work
    async def get_import_results(
        self,
        import_batch_id: UUID7,
        result_status: ImportResultStatus | None = None,
    ) -> list[ImportResult]:
        """Get a list of results for an import batch."""
        return await self.sql_uow.imports.batches.results.get_by_filter(
            import_batch_id=import_batch_id,
            status=result_status,
        )

    @sql_unit_of_work
    async def finalise_record(self, import_record_id: UUID7) -> None:
        """Finalise an import record."""
        await self.sql_uow.imports.update_by_pk(
            import_record_id, status=ImportRecordStatus.COMPLETED
        )
