"""Repositories for imports and associated models."""

from abc import ABC

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_batch import ImportBatch
from app.models.import_record import ImportRecord
from app.repositories.generic import (
    GenericAsyncRepository,
    GenericAsyncSqlRepository,
)


class ImportRepositoryBase(GenericAsyncRepository[ImportRecord], ABC):
    """Abstract implementation of a repository for Imports."""


class ImportRepository(GenericAsyncSqlRepository, ImportRepositoryBase):
    """Concrete implementation of a repository for imports using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the database session."""
        super().__init__(session, ImportRecord)


class ImportBatchRepositoryBase(GenericAsyncRepository[ImportBatch], ABC):
    """Abstract implementation of a repository for ImportBatches."""


class ImportBatchRepository(GenericAsyncSqlRepository, ImportBatchRepositoryBase):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the session."""
        super().__init__(session, ImportBatch)
