"""Repositories for imports and associated models."""

from abc import ABC

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.imports.models.dto import ImportBatchDTO, ImportRecordDTO
from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
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
