"""Import tasks module for the DESTINY Climate and Health Repository API."""

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.service import ReferenceService
from app.domain.robots.external_service import RobotCommunicationService
from app.domain.robots.service import RobotService
from app.persistence.sql.session import db_manager
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.tasks import broker

logger = get_logger()


async def get_unit_of_work(
    session: AsyncSession | None = None,
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on imports."""
    if session is None:
        async with db_manager.session() as s:
            return AsyncSqlUnitOfWork(session=s)

    return AsyncSqlUnitOfWork(session=session)


async def get_reference_service(
    sql_uow: AsyncSqlUnitOfWork | None = None,
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_unit_of_work()
    return ReferenceService(sql_uow=sql_uow)


async def get_robot_service() -> RobotCommunicationService:
    """Return the robot service using the provided unit of work dependencies."""
    robots = RobotService(known_robots=get_settings().known_robots)
    return RobotCommunicationService(robots=robots)


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
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    try:
        await reference_service.collect_and_dispatch_references_for_batch_enhancement(
            batch_enhancement_request,
            robot_service,
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
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    try:
        await reference_service.validate_and_import_batch_enhancement_result(
            batch_enhancement_request,
        )
    except Exception as e:
        logger.exception(
            "Error occurred while validating and importing batch enhancement result"
        )
        await reference_service.mark_batch_enhancement_request_failed(
            batch_enhancement_request_id,
            str(e),
        )
