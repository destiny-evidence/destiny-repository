"""Import tasks module for the DESTINY Climate and Health Repository API."""

from collections.abc import Iterable

from elasticsearch import AsyncElasticsearch
from opentelemetry import trace
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.telemetry.attributes import Attributes, name_span, trace_attribute
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.client import es_manager
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import db_manager
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.tasks import broker

logger = get_logger()
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


async def get_reference_service(
    anti_corruption_service: ReferenceAntiCorruptionService,
    sql_uow: AsyncSqlUnitOfWork,
    es_uow: AsyncESUnitOfWork,
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    return ReferenceService(
        sql_uow=sql_uow,
        es_uow=es_uow,
        anti_corruption_service=anti_corruption_service,
    )


async def get_robot_service(
    robot_anti_corruption_service: RobotAntiCorruptionService,
    sql_uow: AsyncSqlUnitOfWork,
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(
        sql_uow=sql_uow,
        anti_corruption_service=robot_anti_corruption_service,
    )


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
    trace_attribute(
        Attributes.BATCH_ENHANCEMENT_REQUEST_ID, str(batch_enhancement_request_id)
    )
    name_span(f"Dispatch batch enhancement request {batch_enhancement_request_id}")
    sql_uow = await get_sql_unit_of_work()
    es_uow = await get_es_unit_of_work()
    blob_repository = await get_blob_repository()
    reference_anti_corruption_service = ReferenceAntiCorruptionService(blob_repository)
    robot_anti_corruption_service = RobotAntiCorruptionService()
    reference_service = await get_reference_service(
        reference_anti_corruption_service, sql_uow, es_uow
    )
    robot_service = await get_robot_service(robot_anti_corruption_service, sql_uow)
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
    trace_attribute(
        Attributes.BATCH_ENHANCEMENT_REQUEST_ID, str(batch_enhancement_request_id)
    )
    name_span(f"Import batch enhancement result {batch_enhancement_request_id}")
    sql_uow = await get_sql_unit_of_work()
    es_uow = await get_es_unit_of_work()
    blob_repository = await get_blob_repository()
    reference_anti_corruption_service = ReferenceAntiCorruptionService(blob_repository)
    reference_service = await get_reference_service(
        reference_anti_corruption_service, sql_uow, es_uow
    )
    blob_repository = await get_blob_repository()
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    try:
        (
            terminal_status,
            imported_enhancement_ids,
        ) = await reference_service.validate_and_import_batch_enhancement_result(
            batch_enhancement_request,
            blob_repository,
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
        await reference_service.update_batch_enhancement_request_status(
            batch_enhancement_request.id,
            terminal_status,
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

    # Perform robot automations
    await detect_and_dispatch_robot_automations(
        reference_service,
        enhancement_ids=imported_enhancement_ids,
        source_str=f"BatchEnhancementRequest:{batch_enhancement_request.id}",
        skip_robot_id=batch_enhancement_request.robot_id,
    )


@broker.task
async def repair_reference_index() -> None:
    """Async logic for rebuilding the reference index."""
    name_span("Repair reference index")
    logger.info("Repairing reference index")
    sql_uow = await get_sql_unit_of_work()
    es_uow = await get_es_unit_of_work()
    blob_repository = await get_blob_repository()
    reference_anti_corruption_service = ReferenceAntiCorruptionService(blob_repository)
    reference_service = await get_reference_service(
        reference_anti_corruption_service, sql_uow, es_uow
    )
    await reference_service.repopulate_reference_index()


@broker.task
async def repair_robot_automation_percolation_index() -> None:
    """Async logic for rebuilding the robot automation percolation index."""
    name_span("Repair robot automation percolation index")
    logger.info("Repairing robot automation percolation index")
    sql_uow = await get_sql_unit_of_work()
    es_uow = await get_es_unit_of_work()
    blob_repository = await get_blob_repository()
    reference_anti_corruption_service = ReferenceAntiCorruptionService(blob_repository)
    reference_service = await get_reference_service(
        reference_anti_corruption_service, sql_uow, es_uow
    )

    await reference_service.repopulate_robot_automation_percolation_index()


@tracer.start_as_current_span("Detect and dispatch robot automations")
async def detect_and_dispatch_robot_automations(
    reference_service: ReferenceService,
    reference_ids: Iterable[UUID4] | None = None,
    enhancement_ids: Iterable[UUID4] | None = None,
    source_str: str | None = None,
    skip_robot_id: UUID4 | None = None,
) -> list[BatchEnhancementRequest]:
    """
    Request default enhancements for a set of references.

    Technically this is a task distributor, not a task - may live in a higher layer
    later in life.
    """
    requests: list[BatchEnhancementRequest] = []
    robot_automations = await reference_service.detect_robot_automations(
        reference_ids=reference_ids,
        enhancement_ids=enhancement_ids,
    )
    for robot_automation in robot_automations:
        if robot_automation.robot_id == skip_robot_id:
            logger.warning(
                "Detected robot automation loop, skipping."
                " This is likely a problem in the percolation query.",
                extra={
                    "robot_id": robot_automation.robot_id,
                    "source": source_str,
                },
            )
            continue
        enhancement_request = (
            await reference_service.register_batch_reference_enhancement_request(
                enhancement_request=BatchEnhancementRequest(
                    reference_ids=robot_automation.reference_ids,
                    robot_id=robot_automation.robot_id,
                    source=source_str,
                ),
            )
        )
        requests.append(enhancement_request)
        logger.info(
            "Enqueueing enhancement batch for imported references",
            extra={
                "batch_enhancement_request_id": enhancement_request.id,
                "robot_id": robot_automation.robot_id,
            },
        )
        await queue_task_with_trace(
            collect_and_dispatch_references_for_batch_enhancement,
            batch_enhancement_request_id=enhancement_request.id,
        )
    return requests
