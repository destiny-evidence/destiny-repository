"""Repositories for imports and associated models."""

from abc import ABC

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository


class ImportRecordRepositoryBase(
    GenericAsyncRepository[DomainImportRecord, GenericPersistenceType],
    ABC,
):
    """Abstract implementation of a repository for Imports."""


class ImportRecordSQLRepository(
    GenericAsyncSqlRepository[DomainImportRecord, SQLImportRecord],
    ImportRecordRepositoryBase,
):
    """Concrete implementation of a repository for imports using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(
            session,
            DomainImportRecord,
            SQLImportRecord,
        )


class ImportBatchRepositoryBase(
    GenericAsyncRepository[DomainImportBatch, GenericPersistenceType], ABC
):
    """Abstract implementation of a repository for ImportBatches."""


class ImportBatchSQLRepository(
    GenericAsyncSqlRepository[DomainImportBatch, SQLImportBatch],
    ImportBatchRepositoryBase,
):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the session."""
        super().__init__(session, DomainImportBatch, SQLImportBatch)
