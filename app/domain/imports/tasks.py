"""Import tasks module for the DESTINY Climate and Health Repository API."""

from elasticsearch import AsyncElasticsearch
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TaskError
from app.core.logger import get_logger
from app.domain.imports.models.models import ImportBatchStatus
from app.domain.imports.service import ImportService
from app.domain.references.service import ReferenceService
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
    sql_uow: AsyncSqlUnitOfWork | None = None,
) -> ImportService:
    """Return the import service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_sql_unit_of_work()
    return ImportService(sql_uow=sql_uow)


async def get_reference_service(
    sql_uow: AsyncSqlUnitOfWork | None = None,
    es_uow: AsyncESUnitOfWork | None = None,
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_sql_unit_of_work()
    if es_uow is None:
        es_uow = await get_es_unit_of_work()
    return ReferenceService(sql_uow=sql_uow, es_uow=es_uow)


@broker.task
async def process_import_batch(import_batch_id: UUID4) -> None:
    """Async logic for processing an import batch."""
    logger.info("Processing import batch", extra={"import_batch_id": import_batch_id})
    import_service = await get_import_service()
    reference_service = await get_reference_service()

    import_batch = await import_service.get_import_batch(import_batch_id)
    if not import_batch:
        raise TaskError(detail=f"Import batch with ID {import_batch_id} not found.")

    # Import into database
    await import_service.process_batch(import_batch)

    # Update elasticsearch index
    await import_service.update_import_batch_status(
        import_batch.id, ImportBatchStatus.INDEXING
    )
    imported_references = await import_service.get_imported_references_from_batch(
        import_batch_id=import_batch_id
    )

    await reference_service.index_references(
        reference_ids=imported_references,
    )

    await import_service.update_import_batch_status(
        import_batch.id, ImportBatchStatus.COMPLETED
    )
