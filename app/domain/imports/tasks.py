"""Import tasks module for the DESTINY Climate and Health Repository API."""

from elasticsearch import AsyncElasticsearch
from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.domain.references.tasks import (
    detect_and_dispatch_robot_automations,
    get_blob_repository,
)
from app.persistence.es.client import es_manager
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import db_manager
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.tasks import broker

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


async def get_sql_unit_of_work(
    session: AsyncSession | None = None,
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on imports in SQL."""
    if session is None:
        async with db_manager.session() as s:
            return AsyncSqlUnitOfWork(session=s)

    return AsyncSqlUnitOfWork(session=session)


async def get_es_unit_of_work(
    client: AsyncElasticsearch | None = None,
) -> AsyncESUnitOfWork:
    """Return the unit of work for operating on references in ES."""
    if client is None:
        async with es_manager.client() as c:
            return AsyncESUnitOfWork(client=c)

    return AsyncESUnitOfWork(client=client)


async def get_import_service(
    import_anti_corruption_service: ImportAntiCorruptionService | None = None,
    sql_uow: AsyncSqlUnitOfWork | None = None,
) -> ImportService:
    """Return the import service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_sql_unit_of_work()

    if import_anti_corruption_service is None:
        import_anti_corruption_service = ImportAntiCorruptionService()
    return ImportService(
        sql_uow=sql_uow, anti_corruption_service=import_anti_corruption_service
    )


async def get_reference_service(
    reference_anti_corruption_service: ReferenceAntiCorruptionService | None = None,
    sql_uow: AsyncSqlUnitOfWork | None = None,
    es_uow: AsyncESUnitOfWork | None = None,
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_sql_unit_of_work()
    if es_uow is None:
        es_uow = await get_es_unit_of_work()
    if reference_anti_corruption_service is None:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository=blob_repository
        )
    return ReferenceService(
        sql_uow=sql_uow,
        es_uow=es_uow,
        anti_corruption_service=reference_anti_corruption_service,
    )


@broker.task
async def distribute_import_batch(import_batch_id: UUID4) -> None:
    """Async logic for processing an import batch."""
    name_span(f"Distribute import batch {import_batch_id}")
    trace_attribute(Attributes.IMPORT_BATCH_ID, str(import_batch_id))
    sql_uow = await get_sql_unit_of_work()
    import_service = await get_import_service(sql_uow=sql_uow)

    import_batch = await import_service.get_import_batch(import_batch_id)
    await import_service.distribute_import_batch(import_batch)


@broker.task
async def import_reference(
    import_result_id: UUID4, content: str, line_number: int, remaining_retries: int
) -> None:
    """Async logic for importing a reference."""
    name_span(f"Import line {line_number}")
    trace_attribute(Attributes.IMPORT_RESULT_ID, str(import_result_id))
    trace_attribute(Attributes.MESSAGING_RETRIES_REMAINING, remaining_retries)
    sql_uow = await get_sql_unit_of_work()
    es_uow = await get_es_unit_of_work()
    import_service = await get_import_service(sql_uow=sql_uow)
    reference_service = await get_reference_service(sql_uow=sql_uow, es_uow=es_uow)

    import_result = await import_service.get_import_result(
        import_result_id, preload=["import_batch"]
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
            logger.info("No remaining retries for import batch, marking as failed.")
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
