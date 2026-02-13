"""Import tasks module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from opentelemetry import trace
from structlog.contextvars import bound_contextvars

from app.core.config import Environment, get_settings
from app.core.exceptions import SQLIntegrityError
from app.core.telemetry.attributes import (
    Attributes,
    name_span,
    sample_trace,
    trace_attribute,
)
from app.core.telemetry.logger import get_logger
from app.core.telemetry.otel import new_linked_trace
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    DuplicateDetermination,
    PendingEnhancementStatus,
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
settings = get_settings()


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
    name_span("Import robot enhancement batch result")
    trace_attribute(
        Attributes.ROBOT_ENHANCEMENT_BATCH_ID, str(robot_enhancement_batch_id)
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
                results = await reference_service.validate_and_import_robot_enhancement_batch_result(  # noqa: E501
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
            pending_enhancement_ids=list(results.failed_pending_enhancement_ids),
            status=PendingEnhancementStatus.FAILED,
        )

        await reference_service.update_pending_enhancements_status(
            pending_enhancement_ids=list(results.discarded_pending_enhancement_ids),
            status=PendingEnhancementStatus.DISCARDED,
        )

        await reference_service.update_pending_enhancements_status(
            pending_enhancement_ids=list(results.successful_pending_enhancement_ids),
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
                pending_enhancement_ids=list(
                    results.successful_pending_enhancement_ids
                ),
                status=PendingEnhancementStatus.COMPLETED,
            )
        except Exception:
            logger.exception("Error indexing references in Elasticsearch")
            await reference_service.update_pending_enhancements_status(
                pending_enhancement_ids=list(
                    results.successful_pending_enhancement_ids
                ),
                status=PendingEnhancementStatus.INDEXING_FAILED,
            )

        # Perform robot automations
        await reference_service.detect_and_dispatch_robot_automations(
            enhancement_ids=results.imported_enhancement_ids,
            source_str=f"RobotEnhancementBatch:{robot_enhancement_batch.id}",
            skip_robot_id=robot_enhancement_batch.robot_id,
        )


@broker.task
async def repair_reference_index() -> None:
    """Async logic for repairing the reference index."""
    name_span("Repair index")
    trace_attribute(Attributes.DB_COLLECTION_ALIAS_NAME, "reference")
    logger.info("Distributing reference index repair tasks")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        partitions = await reference_service.get_reference_id_partition_boundaries(
            partition_size=settings.es_reference_repair_chunk_size
        )
        for index, (min_id, max_id) in enumerate(partitions, start=1):
            with new_linked_trace(
                "Queue repair index chunk task",
                attributes={Attributes.DB_COLLECTION_ALIAS_NAME: "reference"},
            ):
                await queue_task_with_trace(
                    repair_reference_index_for_chunk,
                    min_id,
                    max_id,
                    index,
                    len(partitions),
                    otel_enabled=settings.otel_enabled,
                )


@broker.task
async def repair_reference_index_for_chunk(
    min_id: UUID, max_id: UUID, index: int, total: int
) -> None:
    """Async logic for repairing a chunk of the reference index."""
    name_span("Repair index chunk")
    trace_attribute(Attributes.DB_COLLECTION_ALIAS_NAME, "reference")
    logger.info(
        "Repairing reference index chunk",
        min_id=str(min_id),
        max_id=str(max_id),
        progress=f"{index:,}/{total:,}",
    )
    if index == 0 or index == total - 1:
        # Explicitly sample first and last chunks so we can monitor for completion
        # and total duration. Note this isn't a perfect science, some chunks may
        # retry and the queue may not be strictly FIFO.
        sample_trace()

    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )
        reference_ids = await reference_service.get_all_reference_ids(
            min_id=min_id, max_id=max_id
        )
        trace_attribute(Attributes.DB_RECORD_COUNT, len(reference_ids))
        await reference_service.index_references(reference_ids)


@broker.task
async def repair_robot_automation_percolation_index() -> None:
    """Async logic for repairing the robot automation percolation index."""
    name_span("Repair index")
    trace_attribute(Attributes.DB_COLLECTION_ALIAS_NAME, "robot_automation_percolation")
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
    name_span("Process reference duplicate decision")
    trace_attribute(
        Attributes.REFERENCE_DUPLICATE_DECISION_ID, str(reference_duplicate_decision_id)
    )
    logger.info(
        "Processing reference duplicate decision",
        reference_duplicate_decision_id=str(reference_duplicate_decision_id),
    )
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

            try:
                await reference_service.process_reference_duplicate_decision(
                    reference_duplicate_decision
                )
            except SQLIntegrityError as e:
                # Only handle race conditions for the expected model.
                if e.lookup_model != "ReferenceDuplicateDecision":
                    raise
                # Rollback to clear the invalid session state before re-fetching.
                await sql_uow.rollback()
                updated_decision = (
                    await reference_service.get_reference_duplicate_decision(
                        reference_duplicate_decision_id
                    )
                )
                if (
                    updated_decision.duplicate_determination
                    != DuplicateDetermination.PENDING
                ):
                    logger.info(
                        "Decision was processed by another worker, skipping.",
                        duplicate_determination=updated_decision.duplicate_determination,
                        collision=e.collision,
                    )
                    return
                raise  # Re-raise if still pending (different integrity issue)


@broker.task(
    schedule=(
        [{"cron": "* * * * *"}]  # Every minute
        if settings.env == Environment.LOCAL
        else None
    )
)
async def expire_and_replace_stale_pending_enhancements() -> None:
    """Expire stale pending enhancements and create replacements."""
    name_span("Expire and replace stale pending enhancements")
    logger.info("Expiring and replacing stale pending enhancements")
    async with get_sql_unit_of_work() as sql_uow, get_es_unit_of_work() as es_uow:
        blob_repository = await get_blob_repository()
        reference_anti_corruption_service = ReferenceAntiCorruptionService(
            blob_repository
        )
        reference_service = await get_reference_service(
            reference_anti_corruption_service, sql_uow, es_uow
        )

        await reference_service.expire_and_replace_stale_pending_enhancements()
