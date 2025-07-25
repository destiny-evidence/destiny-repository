"""Import tasks module for the DESTINY Climate and Health Repository API."""

from elasticsearch import AsyncElasticsearch
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ESError, TaskError
from app.core.logger import get_logger
from app.domain.imports.models.models import ImportBatchStatus
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

logger = get_logger()


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
async def process_import_batch(import_batch_id: UUID4, remaining_retries: int) -> None:
    """Async logic for processing an import batch."""
    logger.info(
        "Processing import batch",
        extra={
            "import_batch_id": import_batch_id,
            "remaining_retries": remaining_retries,
        },
    )
    sql_uow = await get_sql_unit_of_work()
    import_service = await get_import_service(sql_uow=sql_uow)
    reference_service = await get_reference_service(sql_uow=sql_uow)

    import_batch = await import_service.get_import_batch(import_batch_id)
    if not import_batch:
        raise TaskError(detail=f"Import batch with ID {import_batch_id} not found.")
    if import_batch.status in (
        ImportBatchStatus.FAILED,
        ImportBatchStatus.INDEXING_FAILED,
        ImportBatchStatus.COMPLETED,
        ImportBatchStatus.CANCELLED,
    ):
        logger.info(
            "Terminal task received for import batch, not processing.",
            extra={"import_batch_id": import_batch_id, "status": import_batch.status},
        )
        return

    # Import into database
    status = await import_service.process_batch(import_batch, reference_service)

    if status == ImportBatchStatus.RETRYING:
        if remaining_retries:
            logger.info(
                "Retrying import batch.",
                extra={
                    "import_batch_id": import_batch_id,
                    "remaining_retries": remaining_retries,
                },
            )
            await process_import_batch.kiq(import_batch.id, remaining_retries - 1)
        else:
            logger.info(
                "No remaining retries for import batch, marking as failed.",
                extra={
                    "import_batch_id": import_batch_id,
                    "remaining_retries": remaining_retries,
                },
            )
            await import_service.update_import_batch_status(
                import_batch.id, ImportBatchStatus.FAILED
            )
        return

    # Update elasticsearch index
    if status != ImportBatchStatus.INDEXING:
        logger.error(
            "Import batch processing stopped, "
            "elasticsearch indexing and automatic enhancements will not proceed.",
            extra={
                "import_batch_id": import_batch.id,
                "import_batch_status": import_batch.status,
            },
        )
        return

    imported_references = await import_service.get_imported_references_from_batch(
        import_batch_id=import_batch.id
    )
    try:
        await reference_service.index_references(
            reference_ids=imported_references,
        )

    except ESError:
        logger.exception(
            "Error indexing references in Elasticsearch",
            extra={
                "import_batch_id": import_batch.id,
            },
        )
        import_batch_status = ImportBatchStatus.INDEXING_FAILED
    except Exception:
        logger.exception(
            "Unexpected error indexing references in Elasticsearch",
            extra={
                "import_batch_id": import_batch.id,
            },
        )
        import_batch_status = ImportBatchStatus.INDEXING_FAILED

    else:
        import_batch_status = ImportBatchStatus.COMPLETED

    await import_service.update_import_batch_status(
        import_batch.id, import_batch_status
    )
    await import_service.dispatch_import_batch_callback(import_batch)

    # Perform automatic enhancements on imported references
    logger.info("Creating automatic enhancements for imported references")
    requests = await detect_and_dispatch_robot_automations(
        reference_service=reference_service,
        reference_ids=imported_references,
        source_str=f"ImportBatch:{import_batch.id}",
    )
    for request in requests:
        logger.info(
            "Created automatic enhancement request", extra={"request_id": request.id}
        )
