"""Import tasks module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from opentelemetry import trace
from pydantic import UUID7

from app.core.telemetry.attributes import (
    Attributes,
    name_span,
    trace_attribute,
)
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.imports.models.models import ImportResultStatus
from app.domain.imports.service import ImportService
from app.domain.imports.services.anti_corruption_service import (
    ImportAntiCorruptionService,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.tasks import detect_and_dispatch_robot_automations
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.client import es_manager
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import db_manager
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.tasks import broker

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@asynccontextmanager
async def get_sql_unit_of_work() -> AsyncGenerator[AsyncSqlUnitOfWork, None]:
    """Async context manager for SQL unit of work."""
    async with db_manager.session() as s:
        yield AsyncSqlUnitOfWork(session=s)


@asynccontextmanager
async def get_es_unit_of_work() -> AsyncGenerator[AsyncESUnitOfWork, None]:
    """Async context manager for ES unit of work."""
    async with es_manager.client() as c:
        yield AsyncESUnitOfWork(client=c)


async def get_import_service(
    sql_uow: AsyncSqlUnitOfWork,
) -> ImportService:
    """Return the import service using the provided unit of work dependencies."""
    return ImportService(
        sql_uow=sql_uow, anti_corruption_service=ImportAntiCorruptionService()
    )


async def get_reference_service(
    sql_uow: AsyncSqlUnitOfWork,
    es_uow: AsyncESUnitOfWork,
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    return ReferenceService(
        sql_uow=sql_uow,
        es_uow=es_uow,
        anti_corruption_service=ReferenceAntiCorruptionService(BlobRepository()),
    )


@broker.task
async def distribute_import_batch(import_batch_id: UUID7) -> None:
    """Async logic for processing an import batch."""
    name_span(f"Distribute import batch {import_batch_id}")
    trace_attribute(Attributes.IMPORT_BATCH_ID, str(import_batch_id))
    async with get_sql_unit_of_work() as sql_uow:
        import_service = await get_import_service(sql_uow=sql_uow)

        import_batch = await import_service.get_import_batch(import_batch_id)
        await import_service.distribute_import_batch(import_batch)


@broker.task
async def import_reference(
    import_result_id: UUID7, content: str, line_number: int, remaining_retries: int
) -> None:
    """Async logic for importing a reference."""
    name_span(f"Import line {line_number}")
    trace_attribute(Attributes.IMPORT_RESULT_ID, str(import_result_id))
    trace_attribute(Attributes.MESSAGING_RETRIES_REMAINING, remaining_retries)
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        import_service = await get_import_service(sql_uow=sql_uow)
        reference_service = await get_reference_service(sql_uow=sql_uow, es_uow=es_uow)

        import_result = await import_service.get_import_result_with_batch(
            import_result_id
        )
        if not import_result.import_batch:
            msg = "Import result is missing its import batch. This should not happen."
            raise RuntimeError(msg)
        trace_attribute(Attributes.IMPORT_BATCH_ID, str(import_result.import_batch_id))

        import_result = await import_service.import_reference(
            reference_service,
            import_result,
            import_result.import_batch.collision_strategy,
            content,
            line_number,
        )

        if import_result.status == ImportResultStatus.RETRYING:
            if remaining_retries:
                logger.info("Retrying import reference.")
                await queue_task_with_trace(
                    import_reference,
                    import_result.id,
                    content,
                    line_number,
                    remaining_retries - 1,
                )
            else:
                logger.info(
                    "No remaining retries for reference import, marking as failed."
                )
            return

        if (
            import_result.status
            in (
                ImportResultStatus.COMPLETED,
                ImportResultStatus.PARTIALLY_FAILED,
            )
            and import_result.reference_id
        ):
            logger.info("Creating automatic enhancements for imported references")
            requests = await detect_and_dispatch_robot_automations(
                reference_service=reference_service,
                reference_ids=[import_result.reference_id],
                source_str=f"ImportResult:{import_result.id}",
            )
            for request in requests:
                logger.info(
                    "Created automatic enhancement request",
                    enhancement_request_id=str(request.id),
                )
