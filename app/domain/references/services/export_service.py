"""Services for the lifecycle of reference export jobs."""

from uuid import UUID

from opentelemetry import trace

from app.core.config import UploadFile, get_settings
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
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
from app.persistence.es.repository import ES_MAX_PAGE_SIZE
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.es.uow import unit_of_work as es_unit_of_work
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class ReferenceExportService(GenericService[ReferenceAntiCorruptionService]):
    """Export a list of reference ids to a file."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
        access_control_service: ReferenceAccessControlService,
        reference_service: ReferenceService,
    ) -> None:
        """Initialize the service."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._access_control_service = access_control_service
        self._reference_service = reference_service

    @sql_unit_of_work
    async def get(self, export_id: UUID) -> ReferenceExport:
        """Get a reference export by id."""
        return await self.sql_uow.reference_exports.get_by_pk(export_id)

    @sql_unit_of_work
    async def fail(self, export_id: UUID, error: str) -> ReferenceExport:
        """Mark a reference export as failed with the given error message."""
        return await self.sql_uow.reference_exports.update_by_pk(
            pk=export_id,
            status=ExportStatus.FAILED,
            error=error,
        )

    @sql_unit_of_work
    async def _claim(self, export_id: UUID) -> ReferenceExport | None:
        """
        Atomically transition pending → running, returning the claimed row.

        Returns ``None`` if the row was not in `pending`. The fetch happens in
        the same UoW as the update so the caller can't see a row that has
        since been mutated by another transaction.
        """
        updated = await self.sql_uow.reference_exports.bulk_update_by_filter(
            filter_conditions={"id": export_id, "status": ExportStatus.PENDING},
            status=ExportStatus.RUNNING,
        )
        if updated == 0:
            return None
        return await self.sql_uow.reference_exports.get_by_pk(export_id)

    @sql_unit_of_work
    async def _complete(
        self,
        export_id: UUID,
        result_file: BlobStorageFile,
        n_references: int,
    ) -> ReferenceExport:
        """Mark a reference export as completed."""
        return await self.sql_uow.reference_exports.update_by_pk(
            pk=export_id,
            status=ExportStatus.COMPLETED,
            result_file=result_file.to_uri(),
            n_references=n_references,
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
            path="exports",
            filename=f"{export_id}.{export_format.extension}",
            chunk_size=chunk_size,
        )

    async def run(
        self,
        export_id: UUID,
        blob_repository: BlobRepository,
        reference_ids: list[UUID] | None = None,
    ) -> ReferenceExport | None:
        """
        Run a queued reference export end-to-end.

        ``reference_ids`` overrides the ids stored on the export. Returns the
        finished export, or ``None`` if it was not pending.
        """
        export = await self._claim(export_id)
        if export is None:
            logger.info(
                "Skipping reference export, not in pending state",
                reference_export_id=str(export_id),
            )
            return None
        if reference_ids is None:
            reference_ids = export.reference_ids
        if reference_ids is None:
            return await self.fail(export_id, "No reference ids to export.")
        try:
            result_file, n_references = await self.stream_export_file(
                export_id=export.id,
                reference_ids=reference_ids,
                export_format=export.export_format,
                blob_repository=blob_repository,
            )
            completed = await self._complete(export_id, result_file, n_references)
        except Exception as exc:
            logger.exception(
                "Reference export failed", reference_export_id=str(export_id)
            )
            return await self.fail(export_id, f"Failed to run export task: {exc}")
        return completed

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


class SearchExportService(GenericService[ReferenceAntiCorruptionService]):
    """Export the references matching a search query to files."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
        access_control_service: ReferenceAccessControlService,
        reference_service: ReferenceService,
    ) -> None:
        """Initialize the service."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)
        self._search_service = SearchService(anti_corruption_service, sql_uow, es_uow)
        self._reference_export_service = ReferenceExportService(
            anti_corruption_service,
            sql_uow,
            es_uow,
            access_control_service,
            reference_service,
        )

    @sql_unit_of_work
    async def get(self, export_id: UUID) -> SearchExport:
        """Get a search export by id, with its chunks."""
        return await self.sql_uow.search_exports.get_by_pk(
            export_id, preload=["chunks"]
        )

    @sql_unit_of_work
    async def fail(self, export_id: UUID, error: str) -> SearchExport:
        """Mark a search export as failed with the given error message."""
        return await self.sql_uow.search_exports.update_by_pk(pk=export_id, error=error)

    @sql_unit_of_work
    async def request_search_export(
        self,
        query: SearchQuery,
        sort: list[str] | None,
        export_format: ExportFormat = ExportFormat.JSONL,
    ) -> SearchExport:
        """Create a pending search export job."""
        search_export = SearchExport(
            query=query, sort=sort, export_format=export_format, chunks=[]
        )
        await self.sql_uow.search_exports.add(search_export)
        return search_export

    @es_unit_of_work
    async def _collect_search_export_ids(
        self, search_export: SearchExport
    ) -> tuple[list[UUID], bool]:
        """
        Scan the search for up to the result-window cap of reference ids.

        Returns the ids and whether the matching set exceeded the cap.
        """
        cap = SearchService.MAX_RESULT_WINDOW
        reference_ids: list[UUID] = []
        total = 0
        async for page in self._search_service.scan(
            search_export.query,
            sort=search_export.sort,
            limit=cap,
            page_size=ES_MAX_PAGE_SIZE,
            score=not search_export.sort,
        ):
            total = page.total.value
            reference_ids.extend(hit.id for hit in page.hits)
        return reference_ids, total > cap

    @sql_unit_of_work
    async def _add_chunk(
        self, search_export: SearchExport, n_references: int, *, truncated: bool
    ) -> ReferenceExport:
        """Add the export's chunk, raising if it already has one."""
        chunk = await self.sql_uow.reference_exports.add(
            ReferenceExport(
                search_export_id=search_export.id,
                chunk_index=0,
                export_format=search_export.export_format,
            )
        )
        await self.sql_uow.search_exports.update_by_pk(
            pk=search_export.id, n_references=n_references, truncated=truncated
        )
        return chunk

    @sql_unit_of_work
    async def _attach_result_file(
        self, export_id: UUID, result_file: BlobStorageFile
    ) -> SearchExport:
        return await self.sql_uow.search_exports.update_by_pk(
            pk=export_id, result_file=result_file.to_uri()
        )

    async def run(self, export_id: UUID, blob_repository: BlobRepository) -> None:
        """Run a queued search export end-to-end."""
        search_export = await self.get(export_id)
        if search_export.chunks or search_export.error is not None:
            logger.info(
                "Skipping search export, already run",
                search_export_id=str(export_id),
            )
            return
        try:
            reference_ids, truncated = await self._collect_search_export_ids(
                search_export
            )
            chunk = await self._add_chunk(
                search_export, len(reference_ids), truncated=truncated
            )
            finished = await self._reference_export_service.run(
                chunk.id, blob_repository, reference_ids=reference_ids
            )
            if finished and finished.result_file:
                await self._attach_result_file(export_id, finished.result_file)
        except Exception as exc:
            logger.exception("Search export failed", search_export_id=str(export_id))
            await self.fail(export_id, f"Failed to run export task: {exc}")
