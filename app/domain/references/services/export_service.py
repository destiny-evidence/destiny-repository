"""Services for the lifecycle of reference export jobs."""

import contextlib
from uuid import UUID

from opentelemetry import trace

from app.core.config import UploadFile, get_settings
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
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
from app.persistence.es.persistence import ESHit
from app.persistence.es.repository import ES_MAX_PAGE_SIZE
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.es.uow import unit_of_work as es_unit_of_work
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work
from app.utils.aio import prefetch

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
        """Mark an unfinished reference export as failed with the given error."""
        await self.sql_uow.reference_exports.bulk_update_by_filter(
            filter_conditions={
                "id": export_id,
                "status": ExportStatus.sources_of(ExportStatus.FAILED),
            },
            status=ExportStatus.FAILED,
            error=error,
        )
        return await self.sql_uow.reference_exports.get_by_pk(export_id)

    @sql_unit_of_work
    async def _claim(self, export_id: UUID) -> ReferenceExport | None:
        """
        Mark an unfinished export as running and return it, or ``None`` if finished.

        Running exports can be claimed again so a redelivered task can finish one
        whose worker died.
        """
        updated = await self.sql_uow.reference_exports.bulk_update_by_filter(
            filter_conditions={
                "id": export_id,
                "status": ExportStatus.sources_of(ExportStatus.RUNNING),
            },
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
    ) -> ReferenceExport:
        """Mark a running reference export as completed with the given file."""
        updated = await self.sql_uow.reference_exports.bulk_update_by_filter(
            filter_conditions={
                "id": export_id,
                "status": ExportStatus.sources_of(ExportStatus.COMPLETED),
            },
            status=ExportStatus.COMPLETED,
            result_file=result_file.to_uri(),
        )
        export = await self.sql_uow.reference_exports.get_by_pk(export_id)
        if updated and export.search_export_id is not None:
            chunks = await self.sql_uow.reference_exports.find(
                search_export_id=export.search_export_id, limit=2
            )
            # A sole chunk is the whole search export.
            if len(chunks) == 1:
                await self.sql_uow.search_exports.update_by_pk(
                    pk=export.search_export_id, result_file=result_file.to_uri()
                )
        return export

    @sql_unit_of_work
    async def stream_export_file(
        self,
        *,
        export_id: UUID,
        reference_ids: list[UUID],
        export_format: ExportFormat,
        blob_repository: BlobRepository,
    ) -> BlobStorageFile:
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
            fail_on_missing=False,
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
        finished export, or ``None`` if it had already finished.
        """
        export = await self._claim(export_id)
        if export is None:
            logger.info(
                "Skipping reference export, already finished",
                reference_export_id=str(export_id),
            )
            return None
        if export.search_export_id is not None:
            trace_attribute(Attributes.SEARCH_EXPORT_ID, str(export.search_export_id))
            trace_attribute(Attributes.REFERENCE_EXPORT_CHUNK_INDEX, export.chunk_index)
        if reference_ids is None:
            reference_ids = export.reference_ids
        if reference_ids is None:
            return await self.fail(export_id, "No reference ids to export.")
        try:
            result_file = await self.stream_export_file(
                export_id=export.id,
                reference_ids=reference_ids,
                export_format=export.export_format,
                blob_repository=blob_repository,
            )
            completed = await self._complete(export_id, result_file)
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
            reference_ids=reference_ids,
            export_format=export_format,
            n_references=len(reference_ids),
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
        self._access_control_service = access_control_service
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

    @es_unit_of_work
    async def count(self, query: SearchQuery) -> int:
        """Count the references a search export of the query would contain."""
        return (await self._search_service.count(query)).value

    @sql_unit_of_work
    async def request_search_export(
        self,
        query: SearchQuery,
        sort: list[str] | None,
        n_references: int,
        export_format: ExportFormat = ExportFormat.JSONL,
    ) -> SearchExport:
        """Create a pending search export job for a query matching ``n_references``."""
        search_export = SearchExport(
            query=query,
            sort=sort,
            n_references=n_references,
            export_format=export_format,
            chunks=[],
        )
        await self.sql_uow.search_exports.add(search_export)
        return search_export

    @sql_unit_of_work
    async def _add_chunks(
        self, search_export: SearchExport, chunk_sizes: list[int]
    ) -> list[ReferenceExport]:
        """Add chunks of the given sizes, raising if the export already has them."""
        return await self.sql_uow.reference_exports.add_bulk(
            [
                ReferenceExport(
                    search_export_id=search_export.id,
                    chunk_index=chunk_index,
                    export_format=search_export.export_format,
                    n_references=chunk_size,
                )
                for chunk_index, chunk_size in enumerate(chunk_sizes)
            ]
        )

    async def _dispatch(self, chunk: ReferenceExport, hits: list[ESHit]) -> None:
        await queue_task_with_trace(
            ("app.domain.references.tasks", "run_reference_export_task"),
            reference_export_id=chunk.id,
            reference_ids=[hit.id for hit in hits],
            entitlements=self._access_control_service.entitlements,
            otel_enabled=settings.otel_enabled,
        )

    @es_unit_of_work
    async def _collect(
        self, search_export: SearchExport
    ) -> tuple[ReferenceExport, list[UUID]]:
        """Get or allocate the export's single chunk, returning it with its ids."""
        reference_ids = [
            hit.id
            async for page in self._search_service.scan(
                search_export.query,
                sort=search_export.sort,
                page_size=ES_MAX_PAGE_SIZE,
            )
            for hit in page.hits
        ]
        (chunk,) = search_export.chunks or await self._add_chunks(
            search_export, [len(reference_ids)]
        )
        return chunk, reference_ids

    @es_unit_of_work
    async def _distribute(self, search_export: SearchExport) -> None:
        """Allocate the export's chunks and queue a task for each."""
        chunk_size = settings.search_export_chunk_size
        # Each scan page becomes one chunk, so pages are sized to match.
        async with contextlib.aclosing(
            prefetch(
                self._search_service.scan(
                    search_export.query,
                    sort=search_export.sort,
                    page_size=chunk_size,
                )
            )
        ) as pages:
            first_page = await anext(pages)
            n_references = first_page.total.value
            chunks = iter(
                await self._add_chunks(
                    search_export,
                    [
                        min(chunk_size, n_references - start)
                        for start in range(0, n_references, chunk_size)
                    ],
                )
            )
            await self._dispatch(next(chunks), first_page.hits)
            async for page in pages:
                await self._dispatch(next(chunks), page.hits)

    async def run(self, export_id: UUID, blob_repository: BlobRepository) -> None:
        """Run a queued search export end-to-end."""
        search_export = await self.get(export_id)
        if search_export.status in ExportStatus.get_terminal_statuses():
            logger.info(
                "Skipping search export, already finished",
                search_export_id=str(export_id),
            )
            return
        single_file = (
            search_export.n_references or 0
        ) <= settings.max_single_file_search_export_size
        if search_export.chunks and not single_file:
            await self.fail(export_id, "Export was interrupted, please retry.")
            return
        try:
            if single_file:
                chunk, reference_ids = await self._collect(search_export)
                await self._reference_export_service.run(
                    chunk.id, blob_repository, reference_ids=reference_ids
                )
            else:
                await self._distribute(search_export)
        except Exception as exc:
            logger.exception("Search export failed", search_export_id=str(export_id))
            await self.fail(export_id, f"Failed to run export task: {exc}")
