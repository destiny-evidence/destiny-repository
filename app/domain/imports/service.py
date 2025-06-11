"""The service for interacting with and managing imports."""

import httpx
from pydantic import UUID4

from app.core.logger import get_logger
from app.domain.imports.models.models import (
    CollisionStrategy,
    ImportBatch,
    ImportBatchStatus,
    ImportRecord,
    ImportRecordStatus,
    ImportResult,
    ImportResultStatus,
)
from app.domain.references.service import ReferenceService
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work

logger = get_logger()


class ImportService(GenericService):
    """The service which manages our imports and their processing."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    async def _get_import_record(self, import_record_id: UUID4) -> ImportRecord:
        """Get a single import by id."""
        return await self.sql_uow.imports.get_by_pk(import_record_id)

    @unit_of_work
    async def get_import_record(self, import_record_id: UUID4) -> ImportRecord:
        """Get a single import by id."""
        return await self._get_import_record(import_record_id)

    @unit_of_work
    async def get_import_record_with_batches(self, pk: UUID4) -> ImportRecord:
        """Get a single import, eager loading its batches."""
        return await self.sql_uow.imports.get_by_pk(pk, preload=["batches"])

    @unit_of_work
    async def get_import_batch(self, import_batch_id: UUID4) -> ImportBatch:
        """Get a single import by id."""
        return await self.sql_uow.batches.get_by_pk(import_batch_id)

    @unit_of_work
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

    @unit_of_work
    async def get_import_batch_with_results(
        self, import_batch_id: UUID4
    ) -> ImportBatch:
        """Get a single import by id with preloaded results."""
        return await self.sql_uow.batches.get_by_pk(
            import_batch_id, preload=["import_results"]
        )

    @unit_of_work
    async def register_import(self, import_record: ImportRecord) -> ImportRecord:
        """Register an import, persisting it to the database."""
        return await self.sql_uow.imports.add(import_record)

    @unit_of_work
    async def register_batch(self, batch: ImportBatch) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        # Errors if the import record does not exist
        await self._get_import_record(batch.import_record_id)
        return await self.sql_uow.batches.add(batch)

    async def _update_import_batch_status(
        self, import_batch_id: UUID4, status: ImportBatchStatus
    ) -> ImportBatch:
        """Update the status of an import batch."""
        return await self.sql_uow.batches.update_by_pk(import_batch_id, status=status)

    @unit_of_work
    async def update_import_batch_status(
        self, import_batch_id: UUID4, status: ImportBatchStatus
    ) -> ImportBatch:
        """Update the status of an import batch."""
        return await self._update_import_batch_status(import_batch_id, status)

    @unit_of_work
    async def import_reference(
        self,
        import_batch_id: UUID4,
        collision_strategy: CollisionStrategy,
        reference_str: str,
        reference_service: ReferenceService,
        entry_ref: int,
    ) -> None:
        """Import a reference and persist it to the database."""
        import_result = await self.sql_uow.results.add(
            ImportResult(
                import_batch_id=import_batch_id, status=ImportResultStatus.STARTED
            )
        )
        reference_result = await reference_service.ingest_reference(
            reference_str, entry_ref, collision_strategy
        )
        if not reference_result:
            if collision_strategy == CollisionStrategy.DISCARD:
                # Reference was discarded
                return
            msg = """
Reference was not created, discarded or failed.
This should not happen.
"""
            raise RuntimeError(msg)

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

    async def process_batch(self, import_batch: ImportBatch) -> None:
        """
        Process an import batch.

        Actions:
        - Stream the file from the storage URL.
        - Parse each entry of the file via the Reference service.
        - Persist the file via the Reference service.
        - Hit the callback URL with the results.
        """
        await self.update_import_batch_status(
            import_batch.id, ImportBatchStatus.STARTED
        )

        # Note: if parallelised, you would need to create a different
        # reference service with a new uow for each thread.
        try:
            reference_service = ReferenceService(self.sql_uow)
            logger.info("Processing batch", extra={"batch": import_batch})
            async with (
                httpx.AsyncClient() as client,
                client.stream("GET", str(import_batch.storage_url)) as response,
            ):
                response.raise_for_status()
                entry_ref = 1
                async for line in response.aiter_lines():
                    if line.strip():
                        await self.import_reference(
                            import_batch.id,
                            import_batch.collision_strategy,
                            line,
                            reference_service,
                            entry_ref,
                        )
                        entry_ref += 1
        except Exception:
            logger.exception("Failed to process batch", extra={"batch": import_batch})
            await self.update_import_batch_status(
                import_batch.id, ImportBatchStatus.FAILED
            )
            return

        if import_batch.callback_url:
            try:
                async with httpx.AsyncClient(
                    transport=httpx.AsyncHTTPTransport(retries=2)
                ) as client:
                    # Refresh the import batch to get the latest status
                    import_batch = await self.get_import_batch_with_results(
                        import_batch.id
                    )
                    response = await client.post(
                        str(import_batch.callback_url),
                        json=(await import_batch.to_sdk_summary()).model_dump(
                            mode="json"
                        ),
                    )
                    response.raise_for_status()
            except Exception:
                logger.exception(
                    "Failed to send callback", extra={"batch": import_batch}
                )

    @unit_of_work
    async def add_batch_result(
        self,
        import_result: ImportResult,
    ) -> ImportResult:
        """Persist an import result to the database."""
        db_import_result = ImportResult(**import_result.model_dump())
        return await self.sql_uow.results.add(db_import_result)

    @unit_of_work
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

    @unit_of_work
    async def finalise_record(self, import_record_id: UUID4) -> None:
        """Finalise an import record."""
        await self.sql_uow.imports.update_by_pk(
            import_record_id, status=ImportRecordStatus.COMPLETED
        )
