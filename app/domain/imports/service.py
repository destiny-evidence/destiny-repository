"""The service for interacting with and managing imports."""

from pydantic import UUID4

from app.domain.imports.models import ImportBatch, ImportRecord, ImportRecordCreate
from app.persistence.uow import AsyncUnitOfWorkBase


class ImportService:
    """The service which manages our imports and their processing."""

    def __init__(self, uow: AsyncUnitOfWorkBase) -> None:
        """Initialize the service with a unit of work."""
        self.uow = uow

    async def get_import(self, import_id: UUID4) -> ImportRecord | None:
        """Get a single import by id."""
        async with self.uow:
            return await self.uow.imports.get_by_pk(import_id)

    async def get_import_with_batches(self, pk: UUID4) -> ImportRecord | None:
        """Get a single import, eager loading its batches."""
        async with self.uow:
            return await self.uow.imports.get_by_pk(pk, preload=["batches"])

    async def register_import(self, import_record: ImportRecordCreate) -> ImportRecord:
        """Register an import, persisting it to the database."""
        async with self.uow:
            db_import_record = ImportRecord(**import_record.model_dump())
            created = await self.uow.imports.add(db_import_record)
            await self.uow.commit()
            return created

    async def register_batch(self, import_id: UUID4, batch: ImportBatch) -> ImportBatch:
        """Register an import batch, persisting it to the database."""
        async with self.uow:
            import_record = await self.uow.imports.get_by_pk(import_id)
            if not import_record:
                raise RuntimeError
            batch.import_id = import_record.id
            batch = await self.uow.batches.add(batch)
            await self.uow.commit()
            return batch
