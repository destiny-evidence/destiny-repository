"""Services for the lifecycle of reference export jobs."""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
from uuid import UUID

from opentelemetry import trace

from app.core.config import UploadFile, get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    Export,
    ExportFormat,
    ExportStatus,
    ReferenceExport,
    SearchExport,
    SearchQuery,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.access_control_service import (
    ReferenceAccessControlService,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.search_service import SearchService
from app.domain.service import GenericService
from app.persistence.blob.models import BlobStorageFile
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.es.uow import unit_of_work as es_unit_of_work
from app.persistence.sql.repository import GenericAsyncSqlRepository
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)

ExportT = TypeVar("ExportT", bound=Export)


class ExportServiceBase(
    GenericService[ReferenceAntiCorruptionService], Generic[ExportT], ABC
):
    """Shared lifecycle for export jobs."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
        access_control_service: ReferenceAccessControlService,
        reference_service: ReferenceService,
    ) -> None:
        """Initialize the lifecycle service."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._access_control_service = access_control_service
        self._reference_service = reference_service

    @property
    @abstractmethod
    def _repository(self) -> GenericAsyncSqlRepository[ExportT, Any, Any]:
        """The repository for this export kind, from the current SQL unit of work."""

    @property
    @abstractmethod
    def _blob_path(self) -> str:
        """The blob storage subdirectory produced files are written to."""

    @abstractmethod
    async def _resolve_reference_ids(
        self, export: ExportT
    ) -> tuple[list[UUID], dict[str, object]]:
        """
        Resolve a claimed export row to its reference ids and completion extras.

        Returns the ids to stream and any extra fields to persist on completion
        (e.g. a search export's `truncated` flag).
        """

    @sql_unit_of_work
    async def get(self, export_id: UUID) -> ExportT:
        """Get an export job by id."""
        return await self._repository.get_by_pk(export_id)

    @sql_unit_of_work
    async def fail(self, export_id: UUID, error: str) -> ExportT:
        """Mark an export as failed with the given error message."""
        return await self._repository.update_by_pk(
            pk=export_id,
            status=ExportStatus.FAILED,
            error=error,
        )

    @sql_unit_of_work
    async def _claim(self, export_id: UUID) -> ExportT | None:
        """
        Atomically transition pending → running, returning the claimed row.

        Returns ``None`` if the row was not in `pending`. The fetch happens in
        the same UoW as the update so the caller can't see a row that has
        since been mutated by another transaction.
        """
        updated = await self._repository.bulk_update_by_filter(
            filter_conditions={"id": export_id, "status": ExportStatus.PENDING},
            status=ExportStatus.RUNNING,
        )
        if updated == 0:
            return None
        return await self._repository.get_by_pk(export_id)

    @sql_unit_of_work
    async def _complete(
        self,
        export_id: UUID,
        result_file: BlobStorageFile,
        n_references: int,
        **extra: object,
    ) -> ExportT:
        """Mark an export as completed."""
        return await self._repository.update_by_pk(
            pk=export_id,
            status=ExportStatus.COMPLETED,
            result_file=result_file.to_uri(),
            n_references=n_references,
            **extra,
        )

    @sql_unit_of_work
    async def stream_export_file(
        self,
        *,
        export_id: UUID,
        reference_ids: list[UUID],
        export_format: ExportFormat,
        blob_repository: BlobRepository,
    ) -> tuple[BlobStorageFile, int]:
        """Stream references to blob storage in the given format, returning the file."""
        chunk_size = settings.upload_file_chunk_size_override.get(
            UploadFile.SEARCH_EXPORT,
            settings.default_upload_file_chunk_size,
        )
        return await self._reference_service.stream_references_to_blob(
            reference_ids=reference_ids,
            export_format=export_format,
            access_control_service=self._access_control_service,
            blob_repository=blob_repository,
            path=self._blob_path,
            filename=f"{export_id}.{export_format.extension}",
            chunk_size=chunk_size,
        )

    async def run(
        self,
        export_id: UUID,
        blob_repository: BlobRepository,
    ) -> None:
        """Run a queued export job end-to-end."""
        export = await self._claim(export_id)
        if export is None:
            logger.info(
                "Skipping export — not in pending state",
                export_id=str(export_id),
                export_kind=type(self).__name__,
            )
            return
        try:
            reference_ids, extra = await self._resolve_reference_ids(export)
            result_file, n_references = await self.stream_export_file(
                export_id=export.id,
                reference_ids=reference_ids,
                export_format=export.export_format,
                blob_repository=blob_repository,
            )
            await self._complete(export_id, result_file, n_references, **extra)
        except Exception as exc:
            logger.exception(
                "Export job failed",
                export_id=str(export_id),
                export_kind=type(self).__name__,
            )
            await self.fail(export_id, f"Failed to run export task: {exc}")


class ReferenceExportService(ExportServiceBase[ReferenceExport]):
    """Export an explicit list of reference ids to a file."""

    @property
    def _repository(self) -> GenericAsyncSqlRepository[ReferenceExport, Any, Any]:
        return self.sql_uow.reference_exports

    @property
    def _blob_path(self) -> str:
        return "reference_exports"

    async def _resolve_reference_ids(
        self, export: ReferenceExport
    ) -> tuple[list[UUID], dict[str, object]]:
        """Return the ids the reference export already carries."""
        return export.reference_ids, {}

    @sql_unit_of_work
    async def request_reference_export(
        self,
        reference_ids: list[UUID],
        export_format: ExportFormat = ExportFormat.JSONL,
    ) -> ReferenceExport:
        """
        Create a pending reference export job.

        Rejects any id that names a reference that doesn't exist. List size and
        emptiness are enforced at the API layer, so internal callers aren't capped.
        """
        reference_ids = list(dict.fromkeys(reference_ids))
        await self.sql_uow.references.verify_pk_existence(reference_ids)
        reference_export = ReferenceExport(
            reference_ids=reference_ids, export_format=export_format
        )
        await self.sql_uow.reference_exports.add(reference_export)
        return reference_export


class SearchExportService(ExportServiceBase[SearchExport]):
    """Export the references matching a search query to a file."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
        access_control_service: ReferenceAccessControlService,
        reference_service: ReferenceService,
    ) -> None:
        """Initialize the lifecycle service."""
        super().__init__(
            anti_corruption_service,
            sql_uow,
            es_uow,
            access_control_service,
            reference_service,
        )
        self._search_service = SearchService(anti_corruption_service, sql_uow, es_uow)

    @property
    def _repository(self) -> GenericAsyncSqlRepository[SearchExport, Any, Any]:
        return self.sql_uow.search_exports

    @property
    def _blob_path(self) -> str:
        return "search_exports"

    async def _resolve_reference_ids(
        self, export: SearchExport
    ) -> tuple[list[UUID], dict[str, object]]:
        """Run the search once and carry `truncated` through to completion."""
        reference_ids, truncated = await self._collect_search_export_ids(export)
        return reference_ids, {"truncated": truncated}

    @sql_unit_of_work
    async def request_search_export(
        self,
        query: SearchQuery,
        sort: list[str] | None,
        export_format: ExportFormat = ExportFormat.JSONL,
    ) -> SearchExport:
        """Create a pending search export job."""
        search_export = SearchExport(
            query=query, sort=sort, export_format=export_format
        )
        await self.sql_uow.search_exports.add(search_export)
        return search_export

    @es_unit_of_work
    async def _collect_search_export_ids(
        self, search_export: SearchExport
    ) -> tuple[list[UUID], bool]:
        """
        Run the matching search once at the full result window.

        Returns the list of reference IDs and a flag indicating whether the
        matching set exceeded the server's result-window cap (in which case
        only the first window's worth of matches is included). Deep
        pagination beyond the cap will be addressed by #661.
        """
        search_result = await self._search_service.search(
            search_export.query,
            page=1,
            page_size=SearchService.MAX_RESULT_WINDOW,
            sort=search_export.sort,
        )
        # `relation == "gte"` is the common case (ES stopped counting at the
        # track_total_hits threshold); `value > window` covers a server that
        # tracks exact totals beyond our cap.
        total = search_result.total
        truncated = (
            total.relation == "gte" or total.value > SearchService.MAX_RESULT_WINDOW
        )
        return [hit.id for hit in search_result.hits], truncated
