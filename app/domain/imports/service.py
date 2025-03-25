"""The service for interacting with and managing imports."""

from pydantic import UUID4

from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchCreate,
    ImportRecord,
    ImportRecordCreate,
    ImportResult,
    ImportResultCreate,
)
from app.persistence.uow import AsyncUnitOfWorkBase


class ImportService:
    """The service which manages our imports and their processing."""

    def __init__(self, sql_uow: AsyncUnitOfWorkBase) -> None:
        """Initialize the service with a unit of work."""
        self.sql_uow = sql_uow

    async def get_import(self, import_record_id: UUID4) -> ImportRecord | None:
        """Get a single import by id."""
        async with self.sql_uow:
            return await self.sql_uow.imports.get_by_pk(import_record_id)

    async def get_import_with_batches(self, pk: UUID4) -> ImportRecord | None:
        """Get a single import, eager loading its batches."""
        async with self.sql_uow:
            return await self.sql_uow.imports.get_by_pk(pk, preload=["batches"])

    async def register_import(self, import_record: ImportRecordCreate) -> ImportRecord:
        """Register an import, persisting it to the database."""
        async with self.sql_uow:
            db_import_record = ImportRecord(**import_record.model_dump())
            created = await self.sql_uow.imports.add(db_import_record)
            await self.sql_uow.commit()
            return created

    async def register_batch(
        self, import_record_id: UUID4, batch_create: ImportBatchCreate
    ) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        async with self.sql_uow:
            import_record = await self.sql_uow.imports.get_by_pk(import_record_id)
            if not import_record:
                raise RuntimeError
            batch = ImportBatch(
                import_record_id=import_record.id,
                **batch_create.model_dump(),
            )
            batch = await self.sql_uow.batches.add(batch)
            await self.sql_uow.commit()
            return batch

    async def add_batch_result(
        self,
        batch_id: UUID4,
        import_result: ImportResultCreate,
    ) -> ImportResult:
        """Persist an import result to the database."""
        async with self.sql_uow:
            db_import_result = ImportResult(
                **import_result.model_dump(), import_batch_id=batch_id
            )
            created = await self.sql_uow.results.add(db_import_result)
            await self.sql_uow.commit()
            return created
