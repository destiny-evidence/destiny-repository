"""Router for handling management of imports."""

from typing import Annotated

import destiny_sdk
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    AzureJwtAuth,
    CachingStrategyAuth,
    SuccessAuth,
)
from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.imports.models.models import (
    ImportBatch,
    ImportRecord,
    ImportResultStatus,
)
from app.domain.imports.service import ImportService
from app.domain.imports.tasks import process_import_batch
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger()


def unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on imports."""
    return AsyncSqlUnitOfWork(session=session)


def import_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
) -> ImportService:
    """Return the import service using the provided unit of work dependencies."""
    return ImportService(sql_uow=sql_uow)


def choose_auth_strategy() -> AuthMethod:
    """Choose a strategy for our authorization."""
    if settings.env in ("dev", "test"):
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        scope=AuthScopes.IMPORT,
    )


import_auth = CachingStrategyAuth(
    selector=choose_auth_strategy,
)


router = APIRouter(
    prefix="/imports", tags=["imports"], dependencies=[Depends(import_auth)]
)


@router.post("/record/", status_code=status.HTTP_201_CREATED)
async def create_record(
    import_record: destiny_sdk.imports.ImportRecordIn,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> ImportRecord:
    """Create a record for an import process."""
    return await import_service.register_import(ImportRecord.from_sdk_in(import_record))


@router.get("/record/{import_record_id}/")
async def get_record(
    import_record_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportRecord:
    """Get an import from the database."""
    import_record = await import_service.get_import_record(import_record_id)
    if not import_record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record with id {import_record_id} not found.",
        )

    return import_record.to_sdk()


@router.patch(
    "/record/{import_record_id}/finalise/", status_code=status.HTTP_204_NO_CONTENT
)
async def finalise_record(
    import_record_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> None:
    """Finalise an import record."""
    import_record = await import_service.get_import_record(import_record_id)
    if not import_record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record with id {import_record_id} not found.",
        )
    await import_service.finalise_record(import_record_id)


@router.post("/record/{import_record_id}/batch/", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_batch(
    import_record_id: Annotated[UUID4, Path(title="The id of the associated import")],
    batch: destiny_sdk.imports.ImportBatchIn,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatch:
    """Register an import batch for a given import."""
    import_batch = await import_service.register_batch(
        ImportBatch.from_sdk_in(batch, import_record_id)
    )
    logger.info("Enqueueing import batch", extra={"import_batch_id": import_batch.id})
    await process_import_batch.kiq(
        import_batch_id=import_batch.id,
    )
    return import_batch.to_sdk()


@router.get("/record/{import_record_id}/batch/")
async def get_batches(
    import_record_id: Annotated[UUID4, Path(title="The id of the associated import")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> list[destiny_sdk.imports.ImportBatch]:
    """Get batches associated to an import."""
    import_record = await import_service.get_import_record_with_batches(
        import_record_id
    )

    if not import_record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record with id {import_record_id} not found.",
        )
    return [batch.to_sdk() for batch in import_record.batches or []]


@router.get("/batch/{import_batch_id}/")
async def get_batch(
    import_batch_id: Annotated[UUID4, Path(title="The id of the import batch")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatch:
    """Get batches associated to an import."""
    import_batch = await import_service.get_import_batch(import_batch_id)

    if not import_batch:
        raise HTTPException(
            status_code=404,
            detail=f"Import batch with id {import_batch_id} not found.",
        )
    return import_batch.to_sdk()


@router.get("/batch/{import_batch_id}/summary/")
async def get_import_batch_summary(
    import_batch_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatchSummary:
    """Get a summary of an import batch's results."""
    import_batch = await import_service.get_import_batch_with_results(import_batch_id)
    if not import_batch:
        raise HTTPException(
            status_code=404,
            detail=f"Import batch with id {import_batch_id} not found.",
        )
    return import_batch.to_sdk_summary()


@router.get("/batch/{import_batch_id}/results/")
async def get_import_results(
    import_batch_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
    result_status: ImportResultStatus | None = None,
) -> list[destiny_sdk.imports.ImportResult]:
    """Get a list of results for an import batch."""
    import_batch_results = await import_service.get_import_results(
        import_batch_id, result_status
    )
    if not import_batch_results:
        raise HTTPException(
            status_code=404,
            detail=f"No results found for import batch with id {import_batch_id}.",
        )
    return [
        import_batch_results.to_sdk() for import_batch_results in import_batch_results
    ]
