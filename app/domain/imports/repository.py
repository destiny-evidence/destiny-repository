"""Repositories for imports and associated models."""

import uuid
from abc import ABC
from collections import defaultdict
from collections.abc import Collection
from typing import Literal

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

    def __init__(self) -> None:
        """Initialize the repository with the batches repository."""
        super().__init__()


_import_record_sql_preloadable = Literal["batches", "ImportBatch.status"]


class ImportRecordSQLRepository(
    GenericAsyncSqlRepository[
        DomainImportRecord, SQLImportRecord, _import_record_sql_preloadable
    ],
    ImportRecordRepositoryBase,
):
    """Concrete implementation of a repository for imports using SQLAlchemy."""

    def __init__(
        self, session: AsyncSession, batches_repo: "ImportBatchSQLRepository"
    ) -> None:
        """Initialize the repository with the database session and batches repo."""
        super().__init__(
            session,
            DomainImportRecord,
            SQLImportRecord,
        )
        self.batches = batches_repo

    async def get_by_pk(
        self,
        pk: uuid.UUID,
        preload: list[_import_record_sql_preloadable] | None = None,
    ) -> DomainImportRecord:
        """Override to include batch statuses if requested."""
        import_record = await super().get_by_pk(pk, preload)
        if "ImportBatch.status" in (preload or []) and import_record.batches:
            status_sets = await self.batches.get_import_result_status_sets(
                [batch.id for batch in import_record.batches]
            )
            import_record.batches = [
                ImportBatchStatusProjection.get_from_status_set(
                    import_batch, status_sets.get(import_batch.id, set())
                )
                for import_batch in import_record.batches
            ]
        return import_record


class ImportBatchRepositoryBase(
    GenericAsyncRepository[DomainImportBatch, GenericPersistenceType], ABC
):
    """Abstract implementation of a repository for ImportBatches."""

    def __init__(self) -> None:
        """Initialize the repository with the results repository."""
        super().__init__()


_import_batch_sql_preloadable = Literal["import_record", "import_results", "status"]


class ImportBatchSQLRepository(
    GenericAsyncSqlRepository[
        DomainImportBatch,
        SQLImportBatch,
        _import_batch_sql_preloadable,
    ],
    ImportBatchRepositoryBase,
):
    """Repository for ImportBatches using SQLAlchemy."""

    def __init__(
        self, session: AsyncSession, results_repo: "ImportResultSQLRepository"
    ) -> None:
        """Initialize the repository with the session and results repository."""
        super().__init__(session, DomainImportBatch, SQLImportBatch)
        self.results = results_repo

    async def get_import_result_status_sets(
        self, import_batch_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, set[ImportResultStatus]]:
        """
        Get current underlying statuses for multiple import batches.

        Args:
            import_batch_id: The ID of the import batch

        Returns:
            Set of statuses for the import results in the batch

        """
        query = (
            select(
                SQLImportResult.import_batch_id,
                SQLImportResult.status,
            )
            .where(SQLImportResult.import_batch_id.in_(import_batch_ids))
            .distinct()
        )
        results = await self._session.execute(query)
        status_sets = defaultdict(set)
        for import_batch_id, status in results.all():
            status_sets[import_batch_id].add(status)
        return status_sets

    async def get_import_result_status_set(
        self, import_batch_id: uuid.UUID
    ) -> set[ImportResultStatus]:
        """
        Get current underlying statuses for an import batch.

        Args:
            import_batch_id: The ID of the import batch

        Returns:
            Set of statuses for the import results in the batch

        """
        return (await self.get_import_result_status_sets([import_batch_id]))[
            import_batch_id
        ]

    async def get_by_pk(
        self,
        pk: uuid.UUID,
        preload: list[_import_batch_sql_preloadable] | None = None,
    ) -> DomainImportBatch:
        """Override to include derived batch status."""
        import_batch = await super().get_by_pk(pk, preload)
        if "status" in (preload or []):
            import_batch_statuses = await self.get_import_result_status_set(pk)
            return ImportBatchStatusProjection.get_from_status_set(
                import_batch, import_batch_statuses
            )
        return import_batch


class ImportResultRepositoryBase(
    GenericAsyncRepository[DomainImportResult, GenericPersistenceType], ABC
):
    """Abstract implementation of a repository for ImportResults."""


class ImportResultSQLRepository(
    GenericAsyncSqlRepository[
        DomainImportResult, SQLImportResult, Literal["import_batch"]
    ],
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
