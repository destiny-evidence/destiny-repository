"""Import tasks module for the DESTINY Climate and Health Repository API."""

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TaskError
from app.core.logger import get_logger
from app.domain.imports.models.models import ImportBatchStatus
from app.domain.imports.service import ImportService
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


async def get_import_service(
    sql_uow: AsyncSqlUnitOfWork | None = None,
) -> ImportService:
    """Return the import service using the provided unit of work dependencies."""
    if sql_uow is None:
        sql_uow = await get_unit_of_work()
    return ImportService(sql_uow=sql_uow)


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
    import_service = await get_import_service()

    import_batch = await import_service.get_import_batch(import_batch_id)
    if not import_batch:
        raise TaskError(detail=f"Import batch with ID {import_batch_id} not found.")
    if import_batch.status in (
        ImportBatchStatus.FAILED,
        ImportBatchStatus.COMPLETED,
        ImportBatchStatus.CANCELLED,
    ):
        logger.info(
            "Terminal task received for import batch, not processing.",
            extra={"import_batch_id": import_batch_id, "status": import_batch.status},
        )
        return

    status = await import_service.process_batch(import_batch)
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
