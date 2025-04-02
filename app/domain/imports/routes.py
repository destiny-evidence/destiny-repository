"""Router for handling management of imports."""

from typing import Annotated

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
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchCreate,
    ImportBatchSummary,
    ImportRecord,
    ImportRecordCreate,
    ImportResult,
    ImportResultStatus,
)
from app.domain.imports.service import ImportService
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()


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


settings = get_settings()


def choose_auth_strategy() -> AuthMethod:
    """Choose a strategy for our authorization."""
    if settings.env == "dev":
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_tenant_id,
        scope=AuthScopes.IMPORT,
    )


import_auth = CachingStrategyAuth(
    selector=choose_auth_strategy,
)


router = APIRouter(
    prefix="/imports", tags=["imports"], dependencies=[Depends(import_auth)]
)


@router.post("/record/", status_code=status.HTTP_201_CREATED)
async def create_import(
    import_params: ImportRecordCreate,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> ImportRecord:
    """Create a record for an import process."""
    return await import_service.register_import(import_params)


@router.get("/record/{import_record_id}/")
async def get_import(
    import_record_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> ImportRecord:
    """Get an import from the database."""
    import_record = await import_service.get_import(import_record_id)
    if not import_record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record with id {import_record_id} not found.",
        )

    return import_record


@router.post(
    "/record/{import_record_id}/batches/", status_code=status.HTTP_202_ACCEPTED
)
async def create_batch(
    import_record_id: Annotated[UUID4, Path(title="The id of the associated import")],
    batch: ImportBatchCreate,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> ImportBatch:
    """Register an import batch for a given import."""
    return await import_service.register_batch(import_record_id, batch)


@router.get("/record/{import_record_id}/batches/")
async def get_batches(
    import_record_id: Annotated[UUID4, Path(title="The id of the associated import")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> list[ImportBatch]:
    """Get batches associated to an import."""
    import_record = await import_service.get_import_with_batches(import_record_id)

    if not import_record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record with id {import_record_id} not found.",
        )
    return import_record.batches or []


@router.get("/batch/{import_batch_id}/summary/")
async def get_import_batch_summary(
    import_batch_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> ImportBatchSummary:
    """Get a summary of an import batch's results."""
    import_batch_result = await import_service.get_import_batch_summary(import_batch_id)
    if not import_batch_result:
        raise HTTPException(
            status_code=404,
            detail=f"Import batch with id {import_batch_id} not found.",
        )
    return import_batch_result


@router.get("/batch/{import_batch_id}/results/")
async def get_import_results(
    import_batch_id: UUID4,
    import_service: Annotated[ImportService, Depends(import_service)],
    result_status: ImportResultStatus | None = None,
) -> list[ImportResult]:
    """Get a list of results for an import batch."""
    import_batch_results = await import_service.get_import_results(
        import_batch_id, result_status
    )
    if not import_batch_results:
        raise HTTPException(
            status_code=404,
            detail=f"No results found for import batch with id {import_batch_id}.",
        )
    return import_batch_results
