"""Router for handling management of imports."""

from typing import Annotated

import destiny_sdk
from fastapi import APIRouter, Depends, Path, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    CachingStrategyAuth,
    choose_auth_strategy,
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


async def validate_import_record(
    import_record_id: Annotated[UUID4, Path(description="The id of the import")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> None:
    """Validate that the import record exists."""
    await import_service.get_import_record(import_record_id)


def choose_auth_strategy_imports() -> AuthMethod:
    """Choose import scope auth strategy for our imports authorization."""
    return choose_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.IMPORT,
        bypass_auth=settings.running_locally,
    )


import_auth = CachingStrategyAuth(selector=choose_auth_strategy_imports)


router = APIRouter(prefix="/imports", tags=["imports"])

import_record_router = APIRouter(
    prefix="/records",
    tags=["import-records"],
    dependencies=[Depends(import_auth)],
)

import_batch_router = APIRouter(
    prefix="/{import_record_id}/batches",
    tags=["import-batches"],
    dependencies=[Depends(import_auth), Depends(validate_import_record)],
)


@import_record_router.post("/", status_code=status.HTTP_201_CREATED)
async def create_record(
    import_record: destiny_sdk.imports.ImportRecordIn,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportRecordRead:
    """Create a record for an import process."""
    record = await import_service.register_import(
        await ImportRecord.from_sdk(import_record)
    )
    return await record.to_sdk()


@import_record_router.get("/{import_record_id}/")
async def get_record(
    import_record_id: Annotated[UUID4, Path(description="The id of the import")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportRecordRead:
    """Get an import from the database."""
    import_record = await import_service.get_import_record(import_record_id)
    return await import_record.to_sdk()


@import_record_router.patch(
    "/{import_record_id}/finalise/", status_code=status.HTTP_204_NO_CONTENT
)
async def finalise_record(
    import_record_id: Annotated[
        UUID4, Path(description="The id of the import to finalise")
    ],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> None:
    """Finalise an import record."""
    # Raises error if the import record does not exist
    await import_service.finalise_record(import_record_id)


@import_batch_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_batch(
    import_record_id: Annotated[
        UUID4, Path(description="The id of the associated import")
    ],
    batch: destiny_sdk.imports.ImportBatchIn,
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatchRead:
    """Register an import batch for a given import."""
    import_batch = await import_service.register_batch(
        await ImportBatch.from_sdk(batch, import_record_id)
    )
    logger.info("Enqueueing import batch", extra={"import_batch_id": import_batch.id})
    await process_import_batch.kiq(
        import_batch_id=import_batch.id,
        remaining_retries=settings.import_batch_retry_count,
    )
    return await import_batch.to_sdk()


@import_batch_router.get("/")
async def get_batches(
    import_record_id: Annotated[
        UUID4, Path(description="The id of the associated import")
    ],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> list[destiny_sdk.imports.ImportBatchRead]:
    """Get batches associated to an import."""
    import_record = await import_service.get_import_record_with_batches(
        import_record_id
    )
    return [await batch.to_sdk() for batch in import_record.batches or []]


@import_batch_router.get("/{import_batch_id}/")
async def get_batch(
    import_batch_id: Annotated[UUID4, Path(description="The id of the import batch")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatchRead:
    """Get a particular batch."""
    import_batch = await import_service.get_import_batch(import_batch_id)
    return await import_batch.to_sdk()


@import_batch_router.get("/{import_batch_id}/summary/")
async def get_import_batch_summary(
    import_batch_id: Annotated[UUID4, Path(description="The id of the import batch")],
    import_service: Annotated[ImportService, Depends(import_service)],
) -> destiny_sdk.imports.ImportBatchSummary:
    """Get a summary of an import batch's results."""
    import_batch = await import_service.get_import_batch_with_results(import_batch_id)
    return await import_batch.to_sdk_summary()


@import_batch_router.get("/{import_batch_id}/results/")
async def get_import_results(
    import_batch_id: Annotated[UUID4, Path(description="The id of the import batch")],
    import_service: Annotated[ImportService, Depends(import_service)],
    result_status: ImportResultStatus | None = None,
) -> list[destiny_sdk.imports.ImportResultRead]:
    """Get a list of results for an import batch."""
    import_batch_results = await import_service.get_import_results(
        import_batch_id, result_status
    )
    return [
        await import_batch_result.to_sdk()
        for import_batch_result in import_batch_results
    ]


# Must be done after routes defined
import_record_router.include_router(import_batch_router)
router.include_router(import_record_router)
