"""Import tasks module for the DESTINY Climate and Health Repository API."""

from elasticsearch import AsyncElasticsearch
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.domain.references.models.es import ReferenceDocument
from app.domain.references.models.models import BatchEnhancementRequestStatus
from app.domain.references.service import ReferenceService
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService
from app.persistence.blob.repository import BlobRepository
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


async def get_robot_service(
    sql_uow: AsyncSqlUnitOfWork | None = None,
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_sql_unit_of_work()
    return RobotService(sql_uow=sql_uow)


async def get_blob_repository() -> BlobRepository:
    """Return the blob repository using the provided session."""
    return BlobRepository()


async def get_robot_request_dispatcher() -> RobotRequestDispatcher:
    """Return the robot request dispatcher."""
    return RobotRequestDispatcher()


@broker.task
async def collect_and_dispatch_references_for_batch_enhancement(
    batch_enhancement_request_id: UUID4,
) -> None:
    """Async logic for dispatching a batch enhancement request."""
    logger.info(
        "Processing batch enhancement request",
        extra={"batch_enhancement_request_id": batch_enhancement_request_id},
    )
    reference_service = await get_reference_service()
    robot_service = await get_robot_service()
    robot_request_dispatcher = await get_robot_request_dispatcher()
    blob_repository = await get_blob_repository()
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    try:
        await reference_service.collect_and_dispatch_references_for_batch_enhancement(
            batch_enhancement_request,
            robot_service,
            robot_request_dispatcher,
            blob_repository,
        )
    except Exception as e:
        logger.exception("Error occurred while creating batch enhancement request")
        await reference_service.mark_batch_enhancement_request_failed(
            batch_enhancement_request_id,
            str(e),
        )


@broker.task
async def validate_and_import_batch_enhancement_result(
    batch_enhancement_request_id: UUID4,
) -> None:
    """Async logic for validating and importing a batch enhancement result."""
    logger.info(
        "Processing batch enhancement result",
        extra={"batch_enhancement_request_id": batch_enhancement_request_id},
    )
    reference_service = await get_reference_service()
    blob_repository = await get_blob_repository()
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    try:
        terminal_status = (
            await reference_service.validate_and_import_batch_enhancement_result(
                batch_enhancement_request,
                blob_repository,
            )
        )
    except Exception as e:
        logger.exception(
            "Error occurred while validating and importing batch enhancement result"
        )
        await reference_service.mark_batch_enhancement_request_failed(
            batch_enhancement_request_id,
            str(e),
        )
        return

    # Update elasticsearch index
    # For now we naively update all references in the request - this is at worse a
    # superset of the actual enhancement updates.

    await reference_service.update_batch_enhancement_request_status(
        batch_enhancement_request.id,
        BatchEnhancementRequestStatus.INDEXING,
    )

    try:
        await reference_service.index_references(
            reference_ids=batch_enhancement_request.reference_ids,
        )
    except Exception:
        logger.exception(
            "Error indexing references in Elasticsearch",
            extra={
                "batch_enhancement_request_id": batch_enhancement_request_id,
            },
        )
        await reference_service.update_batch_enhancement_request_status(
            batch_enhancement_request.id,
            BatchEnhancementRequestStatus.INDEXING_FAILED,
        )
    else:
        await reference_service.update_batch_enhancement_request_status(
            batch_enhancement_request.id,
            terminal_status,
        )


@broker.task
async def rebuild_reference_index() -> None:
    """Async logic for rebuilding the reference index."""
    logger.info("Rebuilding reference index")
    reference_service = await get_reference_service()
    async with es_manager.client() as client:
        await ReferenceDocument._index.delete(using=client)  # noqa: SLF001
        await ReferenceDocument.init(using=client)

    await reference_service.repopulate_reference_index()
