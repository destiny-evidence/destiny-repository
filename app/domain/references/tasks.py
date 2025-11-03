"""Import tasks module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from uuid import UUID

from opentelemetry import trace
from structlog.contextvars import bound_contextvars

from app.core.telemetry.attributes import Attributes, name_span, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    DuplicateDetermination,
    PendingEnhancementStatus,
    ReferenceWithChangeset,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
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
    reference_duplicate_decision_id: UUID,
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
            # Sanity check to make task safely idempotent
            if (
                reference_duplicate_decision.duplicate_determination
                != DuplicateDetermination.PENDING
            ):
                logger.info(
                    "Duplicate decision already processed, skipping.",
                    duplicate_determination=reference_duplicate_decision.duplicate_determination,
                )
                return

            (
                reference_duplicate_decision,
                decision_changed,
            ) = await reference_service.process_reference_duplicate_decision(
                reference_duplicate_decision
            )

            logger.info(
                "Processed reference duplicate decision",
                active_decision=reference_duplicate_decision.active_decision,
                determination=reference_duplicate_decision.duplicate_determination,
            )

            if reference_duplicate_decision.active_decision and decision_changed:
                reference = await reference_service.get_canonical_reference_with_implied_changeset(  # noqa: E501
                    reference_duplicate_decision.reference_id
                )
                await detect_and_dispatch_robot_automations(
                    reference_service=reference_service,
                    reference=reference,
                    source_str=f"DuplicateDecision:{reference_duplicate_decision.id}",
                )
            else:
                logger.info(
                    "No change to active decision, skipping automations",
                    reference_id=str(reference_duplicate_decision.reference_id),
                )


@tracer.start_as_current_span("Detect and dispatch robot automations")
async def detect_and_dispatch_robot_automations(
    reference_service: ReferenceService,
    reference: ReferenceWithChangeset | None = None,
    enhancement_ids: Iterable[UUID] | None = None,
    source_str: str | None = None,
    skip_robot_id: UUID | None = None,
) -> None:
    """
    Request default enhancements for a set of references.

    Technically this is a task distributor, not a task - may live in a higher layer
    later in life.

    NB this is in a transient state, see comments in
    ReferenceService.detect_robot_automations.
    """
    robot_automations = await reference_service.detect_robot_automations(
        reference=reference,
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
        await reference_service.create_pending_enhancements(
            robot_id=robot_automation.robot_id,
            reference_ids=robot_automation.reference_ids,
            source=source_str,
        )
