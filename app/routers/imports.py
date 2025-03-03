"""Router for handling management of imports."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthScopes, AzureJwtAuth
from app.core.config import get_settings
from app.core.db import get_session
from app.models.import_batch import ImportBatch
from app.models.import_record import ImportRecord, ImportRecordCreate

settings = get_settings()


import_auth = AzureJwtAuth(
    tenant_id=settings.azure_tenant_id,
    application_id=settings.azure_tenant_id,
    scope=AuthScopes.IMPORT,
)


router = APIRouter(
    prefix="/imports", tags=["imports"], dependencies=[Depends(import_auth)]
)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_import(
    import_params: ImportRecordCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ImportRecord:
    """Create a record for an import process."""
    import_record = ImportRecord(**import_params.model_dump())
    session.add(import_record)
    await session.commit()
    await session.refresh(import_record)
    return import_record


@router.get("/{import_id}")
async def get_import(
    import_id: UUID4, session: Annotated[AsyncSession, Depends(get_session)]
) -> ImportRecord:
    """Get an import from the database."""
    import_record = await session.get(ImportRecord, import_id)
    if not import_record:
        raise HTTPException(
            status_code=404, detail=f"Import record with id {import_id} not found."
        )

    return import_record


@router.post("/{import_id}/batches", status_code=status.HTTP_202_ACCEPTED)
async def create_batch(
    import_id: Annotated[UUID4, Path(title="The id of the associated import")],
    batch: ImportBatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ImportBatch:
    """Register an import batch for a given import."""
    batch.import_id = import_id
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


@router.get("/{import_id}/batches")
async def get_batches(
    import_id: Annotated[UUID4, Path(title="The id of the associated import")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ImportBatch]:
    """Get batches associated to an import."""
    import_record = await session.get(ImportRecord, import_id)
    if not import_record:
        raise HTTPException(
            status_code=404, detail=f"Import record with id {import_id} not found."
        )
    return await import_record.awaitable_attrs.batches
