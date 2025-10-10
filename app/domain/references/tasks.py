"""Import tasks module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from uuid import UUID

from opentelemetry import trace
from pydantic import UUID4
from structlog.contextvars import bound_contextvars

from app.core.telemetry.attributes import Attributes, name_span, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    EnhancementRequest,
    EnhancementRequestStatus,
    PendingEnhancementStatus,
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
async def collect_and_dispatch_references_for_enhancement(
    enhancement_request_id: UUID4,
) -> None:
    """Async logic for dispatching a enhancement request."""
    logger.info("Processing enhancement request")
    trace_attribute(Attributes.ENHANCEMENT_REQUEST_ID, str(enhancement_request_id))
    name_span(f"Dispatch enhancement request {enhancement_request_id}")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        robot_anti_corruption_service = RobotAntiCorruptionService()
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        robot_service = await get_robot_service(robot_anti_corruption_service, sql_uow)
        robot_request_dispatcher = await get_robot_request_dispatcher()
        enhancement_request = await reference_service.get_enhancement_request(
            enhancement_request_id
        )
        trace_attribute(Attributes.ROBOT_ID, str(enhancement_request.robot_id))

        try:
            with bound_contextvars(
                robot_id=str(enhancement_request.robot_id),
            ):
                # Collect and dispatch references for the enhancement request
                await reference_service.collect_and_dispatch_references_for_enhancement(
                    enhancement_request,
                    robot_service,
                    robot_request_dispatcher,
                    blob_repository,
                )
        except Exception as e:
            logger.exception("Error occurred while creating enhancement request")
            await reference_service.mark_enhancement_request_failed(
                enhancement_request_id,
                str(e),
            )


@broker.task
async def validate_and_import_enhancement_result(
    enhancement_request_id: UUID4,
) -> None:
    """Async logic for validating and importing an enhancement result."""
    logger.info("Processing enhancement request result")
    trace_attribute(Attributes.ENHANCEMENT_REQUEST_ID, str(enhancement_request_id))
    name_span(f"Import enhancement result for request {enhancement_request_id}")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        enhancement_request = await reference_service.get_enhancement_request(
            enhancement_request_id
        )
        trace_attribute(Attributes.ROBOT_ID, str(enhancement_request.robot_id))

        try:
            with bound_contextvars(
                robot_id=str(enhancement_request.robot_id),
            ):
                # Validate and import the enhancement result
                (
                    terminal_status,
                    imported_enhancement_ids,
                ) = await reference_service.validate_and_import_enhancement_result(
                    enhancement_request,
                    blob_repository,
                )
        except Exception as exc:
            logger.exception(
                "Error occurred while validating and importing enhancement result"
            )
            await reference_service.mark_enhancement_request_failed(
                enhancement_request_id,
                str(exc),
            )
            return

        # Update elasticsearch index
        # For now we naively update all references in the request - this is at worse a
        # superset of the actual enhancement updates.

        await reference_service.update_enhancement_request_status(
            enhancement_request.id,
            EnhancementRequestStatus.INDEXING,
        )

        try:
            await reference_service.index_references(
                reference_ids=enhancement_request.reference_ids,
            )
            await reference_service.update_enhancement_request_status(
                enhancement_request.id,
                terminal_status,
            )
        except Exception:
            logger.exception("Error indexing references in Elasticsearch")
            await reference_service.update_enhancement_request_status(
                enhancement_request.id,
                EnhancementRequestStatus.INDEXING_FAILED,
            )

        # Perform robot automations
        await detect_and_dispatch_robot_automations(
            reference_service,
            enhancement_ids=imported_enhancement_ids,
            source_str=f"EnhancementRequest:{enhancement_request.id}",
            skip_robot_id=enhancement_request.robot_id,
        )


@broker.task
async def validate_and_import_robot_enhancement_batch_result(
    robot_enhancement_batch_id: UUID,
) -> None:
    """Async logic for validating and importing a robot enhancement batch result."""
    logger.info("Processing robot enhancement batch result")
    trace_attribute(
        Attributes.ROBOT_ENHANCEMENT_BATCH_ID, str(robot_enhancement_batch_id)
    )
    name_span(
        f"Import robot enhancement batch result for batch {robot_enhancement_batch_id}"
    )
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        robot_enhancement_batch = await reference_service.get_robot_enhancement_batch(
            robot_enhancement_batch_id, preload=["pending_enhancements"]
        )
        trace_attribute(Attributes.ROBOT_ID, str(robot_enhancement_batch.robot_id))

        try:
            with bound_contextvars(
                robot_id=str(robot_enhancement_batch.robot_id),
            ):
                # Validate and import the enhancement result
                (
                    imported_enhancement_ids,
                    successful_pending_enhancement_ids,
                    failed_pending_enhancement_ids,
                ) = await reference_service.validate_and_import_robot_enhancement_batch_result(  # noqa: E501
                    robot_enhancement_batch,
                    blob_repository,
                )
        except Exception as exc:
            logger.exception(
                "Error occurred while validating and importing a robot enhancement batch result"  # noqa: E501
            )
            await reference_service.mark_robot_enhancement_batch_failed(
                robot_enhancement_batch_id,
                str(exc),
            )
            return

        await reference_service.update_pending_enhancements_status(
            pending_enhancement_ids=list(failed_pending_enhancement_ids),
            status=PendingEnhancementStatus.FAILED,
        )

        await reference_service.update_pending_enhancements_status(
            pending_enhancement_ids=list(successful_pending_enhancement_ids),
            status=PendingEnhancementStatus.INDEXING,
        )

        try:
            await reference_service.index_references(
                reference_ids=[
                    pe.reference_id
                    for pe in (robot_enhancement_batch.pending_enhancements or [])
                ],
            )

            await reference_service.update_pending_enhancements_status(
                pending_enhancement_ids=list(successful_pending_enhancement_ids),
                status=PendingEnhancementStatus.COMPLETED,
            )
        except Exception:
            logger.exception("Error indexing references in Elasticsearch")
            await reference_service.update_pending_enhancements_status(
                pending_enhancement_ids=list(successful_pending_enhancement_ids),
                status=PendingEnhancementStatus.INDEXING_FAILED,
            )

        # Perform robot automations
        await detect_and_dispatch_robot_automations(
            reference_service,
            enhancement_ids=imported_enhancement_ids,
            source_str=f"RobotEnhancementBatch:{robot_enhancement_batch.id}",
            skip_robot_id=robot_enhancement_batch.robot_id,
        )


@broker.task
async def repair_reference_index() -> None:
    """Async logic for rebuilding the reference index."""
    name_span("Repair reference index")
    logger.info("Repairing reference index")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        await reference_service.repopulate_reference_index()


@broker.task
async def repair_robot_automation_percolation_index() -> None:
    """Async logic for rebuilding the robot automation percolation index."""
    name_span("Repair robot automation percolation index")
    logger.info("Repairing robot automation percolation index")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )

        await reference_service.repopulate_robot_automation_percolation_index()


@broker.task
async def process_reference_duplicate_decision(
    reference_duplicate_decision_id: UUID4,
) -> None:
    """Task to process a reference duplicate decision."""
    logger.info(
        "Processing reference duplicate decision",
        reference_duplicate_decision_id=str(reference_duplicate_decision_id),
    )
    name_span(f"Process reference duplicate decision {reference_duplicate_decision_id}")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        reference_duplicate_decision = (
            await reference_service.get_reference_duplicate_decision(
                reference_duplicate_decision_id
            )
        )
        trace_attribute(
            Attributes.REFERENCE_ID, str(reference_duplicate_decision.reference_id)
        )
        with bound_contextvars(
            reference_id=str(reference_duplicate_decision.reference_id),
        ):
            reference_duplicate_decision = (
                await reference_service.process_reference_duplicate_decision(
                    reference_duplicate_decision
                )
            )
            logger.info(
                "Processed reference duplicate decision",
                active_decision=reference_duplicate_decision.active_decision,
                determination=reference_duplicate_decision.duplicate_determination,
            )

            if reference_duplicate_decision.active_decision:
                requests = await detect_and_dispatch_robot_automations(
                    reference_service=reference_service,
                    reference_ids=[
                        # Automate on the canonical reference if it exists,
                        # otherwise the base reference (which is either a canonical
                        # reference or needing more information to deduplicate).
                        reference_duplicate_decision.canonical_reference_id
                        or reference_duplicate_decision.reference_id
                    ],
                    source_str=f"DuplicateDecision:{reference_duplicate_decision.id}",
                )
                for request in requests:
                    logger.info(
                        "Created automatic enhancement request",
                        enhancement_request_id=str(request.id),
                    )


@tracer.start_as_current_span("Detect and dispatch robot automations")
async def detect_and_dispatch_robot_automations(
    reference_service: ReferenceService,
    reference_ids: Iterable[UUID4] | None = None,
    enhancement_ids: Iterable[UUID4] | None = None,
    source_str: str | None = None,
    skip_robot_id: UUID4 | None = None,
) -> list[EnhancementRequest]:
    """
    Request default enhancements for a set of references.

    Technically this is a task distributor, not a task - may live in a higher layer
    later in life.
    """
    requests: list[EnhancementRequest] = []
    robot_automations = await reference_service.detect_robot_automations(
        reference_ids=reference_ids,
        enhancement_ids=enhancement_ids,
    )
    for robot_automation in robot_automations:
        if robot_automation.robot_id == skip_robot_id:
            logger.warning(
                "Detected robot automation loop, skipping."
                " This is likely a problem in the percolation query.",
                robot_id=str(robot_automation.robot_id),
                source=source_str,
            )
            continue
        enhancement_request = (
            await reference_service.register_reference_enhancement_request(
                enhancement_request=EnhancementRequest(
                    reference_ids=robot_automation.reference_ids,
                    robot_id=robot_automation.robot_id,
                    source=source_str,
                ),
            )
        )
        requests.append(enhancement_request)
    return requests
