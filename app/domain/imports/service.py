"""The service for interacting with and managing imports."""

import httpx
from pydantic import UUID4

from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchCreate,
    ImportBatchStatus,
    ImportBatchSummary,
    ImportRecord,
    ImportRecordCreate,
    ImportResult,
    ImportResultCreate,
    ImportResultStatus,
)
from app.domain.references.service import ReferenceService
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


class ImportService(GenericService):
    """The service which manages our imports and their processing."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    @unit_of_work
    async def get_import_record(self, import_record_id: UUID4) -> ImportRecord | None:
        """Get a single import by id."""
        return await self.sql_uow.imports.get_by_pk(import_record_id)

    @unit_of_work
    async def get_import_record_with_batches(self, pk: UUID4) -> ImportRecord | None:
        """Get a single import, eager loading its batches."""
        return await self.sql_uow.imports.get_by_pk(pk, preload=["batches"])

    @unit_of_work
    async def get_import_batch(self, import_batch_id: UUID4) -> ImportBatch | None:
        """Get a single import by id."""
        return await self.sql_uow.batches.get_by_pk(import_batch_id)

    @unit_of_work
    async def register_import(self, import_record: ImportRecordCreate) -> ImportRecord:
        """Register an import, persisting it to the database."""
        db_import_record = ImportRecord(**import_record.model_dump())
        return await self.sql_uow.imports.add(db_import_record)

    @unit_of_work
    async def register_batch(
        self, import_record_id: UUID4, batch_create: ImportBatchCreate
    ) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        import_record = await self.sql_uow.imports.get_by_pk(import_record_id)
        if not import_record:
            raise RuntimeError
        batch = ImportBatch(
            import_record_id=import_record.id,
            **batch_create.model_dump(),
        )
        return await self.sql_uow.batches.add(batch)

    async def import_reference(
        self,
        import_batch_id: UUID4,
        reference_str: str,
        reference_service: ReferenceService,
        entry_ref: int,
    ) -> None:
        """Import a reference and persist it to the database."""
        import_result = await self.sql_uow.results.add(
            ImportResult(import_batch_id=import_batch_id)
        )
        import_result = await self.sql_uow.results.update_by_pk(
            import_result.id, status=ImportResultStatus.STARTED
        )
        reference_result = await reference_service.ingest_reference(
            reference_str, entry_ref
        )
        if not reference_result.reference:
            # Reference was not created
            import_result = await self.sql_uow.results.update_by_pk(
                import_result.id,
                failure_details=reference_result.error_str,
                status=ImportResultStatus.FAILED,
            )
        elif reference_result.errors:
            # Reference was created, but errors occurred
            import_result = await self.sql_uow.results.update_by_pk(
                import_result.id,
                status=ImportResultStatus.PARTIALLY_FAILED,
                reference_id=reference_result.reference.id,
                failure_details=reference_result.error_str,
            )
            import_result.failure_details = "\n\n".join(reference_result.errors)
        else:
            import_result = await self.sql_uow.results.update_by_pk(
                import_result.id, status=ImportResultStatus.COMPLETED
            )
            await self.sql_uow.results.update_by_pk(
                import_result.id,
                status=ImportResultStatus.COMPLETED,
                reference_id=reference_result.reference.id,
            )

    @unit_of_work
    async def process_batch(self, import_batch: ImportBatch) -> None:
        """
        Process an import batch.

        Actions:
        - Stream the file from the storage URL.
        - Parse each entry of the file via the Reference service.
        - Persist the file via the Reference service.
        - Hit the callback URL with the results.
        """
        await self.sql_uow.batches.update_by_pk(
            import_batch.id, import_batch_status=ImportBatchStatus.STARTED
        )

        # Note: if parallelised, you would need to create a different
        # reference service with a new uow for each thread.
        reference_service = ReferenceService(self.sql_uow)
        async with (
            httpx.AsyncClient() as client,
            client.stream("GET", str(import_batch.storage_url)) as response,
        ):
            response.raise_for_status()
            i = 1
            async for line in response.aiter_lines():
                if line.strip():
                    await self.import_reference(
                        import_batch.id, line, reference_service, i
                    )
                    i += 1

        await self.sql_uow.batches.update_by_pk(
            import_batch.id, import_batch_status=ImportBatchStatus.COMPLETED
        )

    @unit_of_work
    async def add_batch_result(
        self,
        batch_id: UUID4,
        import_result: ImportResultCreate,
    ) -> ImportResult:
        """Persist an import result to the database."""
        db_import_result = ImportResult(
            **import_result.model_dump(), import_batch_id=batch_id
        )
        return await self.sql_uow.results.add(db_import_result)

    @unit_of_work
    async def get_import_batch_summary(
        self, import_batch_id: UUID4
    ) -> ImportBatchSummary | None:
        """Get an import batch with its results."""
        import_batch = await self.sql_uow.batches.get_by_pk(
            import_batch_id, preload=["import_results"]
        )
        if not import_batch:
            return None
        result_summary: dict[ImportResultStatus, int] = dict.fromkeys(
            ImportResultStatus, 0
        )
        failure_details: list[str] = []
        for result in import_batch.import_results or []:
            result_summary[result.status] += 1
            if (
                result.status
                in (
                    ImportResultStatus.FAILED,
                    ImportResultStatus.PARTIALLY_FAILED,
                )
                and result.failure_details
            ):
                failure_details.append(result.failure_details)
        return ImportBatchSummary(
            **import_batch.model_dump(),
            results=result_summary,
            failure_details=failure_details,
        )

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
