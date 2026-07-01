"""Service for the lifecycle of reference search-export jobs."""

from uuid import UUID

from opentelemetry import trace

from app.core.config import UploadFile, get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    ExportFormat,
    SearchExport,
    SearchExportStatus,
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
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class SearchExportService(GenericService[ReferenceAntiCorruptionService]):
    """Service for the lifecycle of reference search-export jobs."""

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
        self._search_service = SearchService(anti_corruption_service, sql_uow, es_uow)
        self._access_control_service = access_control_service
        self._reference_service = reference_service

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

    @sql_unit_of_work
    async def get_search_export(self, search_export_id: UUID) -> SearchExport:
        """Get a search export job by id."""
        return await self.sql_uow.search_exports.get_by_pk(search_export_id)

    @sql_unit_of_work
    async def _claim_search_export(self, search_export_id: UUID) -> SearchExport | None:
        """
        Atomically transition pending → running, returning the claimed row.

        Returns ``None`` if the row was not in `pending`. The fetch happens in
        the same UoW as the update so the caller can't see a row that has
        since been mutated by another transaction.
        """
        updated = await self.sql_uow.search_exports.bulk_update_by_filter(
            filter_conditions={
                "id": search_export_id,
                "status": SearchExportStatus.PENDING,
            },
            status=SearchExportStatus.RUNNING,
        )
        if updated == 0:
            return None
        return await self.sql_uow.search_exports.get_by_pk(search_export_id)

    @sql_unit_of_work
    async def _complete_search_export(
        self,
        search_export_id: UUID,
        result_file: BlobStorageFile,
        n_references: int,
        *,
        truncated: bool,
    ) -> SearchExport:
        """Mark a search export as completed."""
        return await self.sql_uow.search_exports.update_by_pk(
            pk=search_export_id,
            status=SearchExportStatus.COMPLETED,
            result_file=result_file,
            n_references=n_references,
            truncated=truncated,
        )

    @sql_unit_of_work
    async def fail_search_export(
        self, search_export_id: UUID, error: str
    ) -> SearchExport:
        """Mark a search export as failed with the given error message."""
        return await self.sql_uow.search_exports.update_by_pk(
            pk=search_export_id,
            status=SearchExportStatus.FAILED,
            error=error,
        )

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

    @sql_unit_of_work
    async def _stream_search_export(
        self,
        search_export: SearchExport,
        reference_ids: list[UUID],
        blob_repository: BlobRepository,
    ) -> tuple[BlobStorageFile, int]:
        """Stream matching references to blob storage in the export's format."""
        chunk_size = settings.upload_file_chunk_size_override.get(
            UploadFile.SEARCH_EXPORT,
            settings.default_upload_file_chunk_size,
        )
        return await self._reference_service.stream_references_to_blob(
            reference_ids=reference_ids,
            export_format=search_export.export_format,
            access_control_service=self._access_control_service,
            blob_repository=blob_repository,
            path="search_exports",
            filename=f"{search_export.id}.{search_export.export_format.extension}",
            chunk_size=chunk_size,
        )

    async def run_search_export(
        self,
        search_export_id: UUID,
        blob_repository: BlobRepository,
    ) -> None:
        """Run a queued search export job end-to-end."""
        # Conditional pending→running keeps redeliveries from clobbering a row
        # that's already running, completed, or failed.
        search_export = await self._claim_search_export(search_export_id)
        if search_export is None:
            logger.info(
                "Skipping search export — not in pending state",
                search_export_id=str(search_export_id),
            )
            return
        try:
            reference_ids, truncated = await self._collect_search_export_ids(
                search_export
            )
            result_file, n_references = await self._stream_search_export(
                search_export, reference_ids, blob_repository
            )
            await self._complete_search_export(
                search_export_id,
                result_file,
                n_references,
                truncated=truncated,
            )
        except Exception as exc:
            logger.exception(
                "Search export job failed",
                search_export_id=str(search_export_id),
            )
            await self.fail_search_export(
                search_export_id, f"Failed to run export task: {exc}"
            )
