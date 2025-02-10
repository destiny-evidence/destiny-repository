"""Router for handling management of imports."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.import_record import ImportRecord, ImportRecordCreate

router = APIRouter(prefix="/imports", tags=["imports"])


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
