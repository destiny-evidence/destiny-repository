"""Repositories for imports and associated models."""

import uuid
from abc import ABC

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telemetry.repository import trace_repository_method
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
from app.domain.imports.models.projections import ImportBatchStatusProjection
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
)
from app.domain.imports.models.sql import (
    ImportResult as SQLImportResult,
)
from app.persistence.generics import GenericPersistenceType
from app.persistence.repository import GenericAsyncRepository
from app.persistence.sql.repository import GenericAsyncSqlRepository

tracer = trace.get_tracer(__name__)


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

    async def _get_import_result_status_set(
        self, import_batch_id: uuid.UUID
    ) -> set[ImportResultStatus]:
        """
        Get current underlying statuses for an import batch.

        Args:
            import_batch_id: The ID of the import batch

        Returns:
            Set of statuses for the import results in the batch

        """
        query = select(
            SQLImportResult.status.distinct(),
        ).where(SQLImportResult.import_batch_id == import_batch_id)
        results = await self._session.execute(query)
        return {row[0] for row in results.all()}

    async def get_by_pk(
        self, pk: uuid.UUID, preload: list[str] | None = None
    ) -> DomainImportBatch:
        """Override to include derived batch status."""
        import_batch = await super().get_by_pk(pk, preload)
        if "status" in (preload or []):
            import_batch_statuses = await self._get_import_result_status_set(pk)
            return ImportBatchStatusProjection.get_from_status_set(
                import_batch, import_batch_statuses
            )
        return import_batch


class ImportResultRepositoryBase(
    GenericAsyncRepository[DomainImportResult, GenericPersistenceType], ABC
):
    """Abstract implementation of a repository for ImportResults."""


class ImportResultSQLRepository(
    GenericAsyncSqlRepository[DomainImportResult, SQLImportResult],
    ImportResultRepositoryBase,
):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with the session."""
        super().__init__(session, DomainImportResult, SQLImportResult)

    @trace_repository_method(tracer)
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
        results = await self._session.execute(query)
        return [result.to_domain() for result in results.scalars().all()]
