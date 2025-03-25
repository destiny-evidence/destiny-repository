"""Repositories for imports and associated models."""

import asyncio
import uuid
from abc import ABC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.models.dto import (
    ImportBatchDTO,
    ImportRecordDTO,
    ImportResultDTO,
)
from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.models import (
    ImportResult as DomainImportResult,
)
from app.domain.imports.models.models import (
    ImportResultStatus,
)
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
)
from app.domain.imports.models.sql import (
    ImportResult as SQLImportResult,
)
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository


class ImportRecordRepositoryBase(
    GenericAsyncRepository[
        ImportRecordDTO,
        DomainImportRecord,
    ],
    ABC,
):
    """Abstract implementation of a repository for Imports."""


class ImportRecordSQLRepository(
    GenericAsyncSqlRepository[ImportRecordDTO, DomainImportRecord, SQLImportRecord],
    ImportRecordRepositoryBase,
):
    """Concrete implementation of a repository for imports using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            ImportRecordDTO,
            DomainImportRecord,
            SQLImportRecord,
        )


class ImportBatchRepositoryBase(
    GenericAsyncRepository[ImportBatchDTO, DomainImportBatch], ABC
):
    """Abstract implementation of a repository for ImportBatches."""


class ImportBatchSQLRepository(
    GenericAsyncSqlRepository[ImportBatchDTO, DomainImportBatch, SQLImportBatch],
    ImportBatchRepositoryBase,
):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the session."""
        super().__init__(session, ImportBatchDTO, DomainImportBatch, SQLImportBatch)


class ImportResultRepositoryBase(
    GenericAsyncRepository[ImportResultDTO, DomainImportResult], ABC
):
    """Abstract implementation of a repository for ImportResults."""


class ImportResultSQLRepository(
    GenericAsyncSqlRepository[ImportResultDTO, DomainImportResult, SQLImportResult],
    ImportResultRepositoryBase,
):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the session."""
        super().__init__(session, ImportResultDTO, DomainImportResult, SQLImportResult)

    async def get_by_filter(
        self,
        import_batch_id: uuid.UUID | None = None,
        status: ImportResultStatus | None = None,
    ) -> list[DomainImportResult]:
        """Get a list of import results based on the provided filters."""
        query = select(SQLImportResult)
        if import_batch_id:
            query = query.where(SQLImportResult.import_batch_id == import_batch_id)
        if status:
            query = query.where(SQLImportResult.status == status)
        result = await self._session.execute(query)
        dtos = await asyncio.gather(
            *(ImportResultDTO.from_sql(r) for r in result.scalars())
        )
        return await asyncio.gather(*(dtos.to_domain() for dtos in dtos))
