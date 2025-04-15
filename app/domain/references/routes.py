"""Router for handling management of imports."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    AzureJwtAuth,
    CachingStrategyAuth,
    SuccessAuth,
)
from app.core.config import get_settings
from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierSearch,
    ExternalIdentifierType,
    Reference,
)
from app.domain.references.service import ReferenceService
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
) -> ReferenceService:
    """Return the import service using the provided unit of work dependencies."""
    return ReferenceService(sql_uow=sql_uow)


settings = get_settings()


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
    prefix="/references", tags=["references"], dependencies=[Depends(import_auth)]
)


@router.get("/{reference_id}/")
async def get_reference(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(import_service)],
) -> Reference:
    """Create a record for an import process."""
    reference = await reference_service.get_reference(reference_id)
    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference with id {reference_id} not found.",
        )
    return reference


@router.get("/")
async def get_reference_from_identifier(
    identifier: str,
    identifier_type: ExternalIdentifierType,
    reference_service: Annotated[ReferenceService, Depends(import_service)],
    other_identifier_name: str | None = None,
) -> Reference:
    """Create a record for an import process."""
    external_identifier = ExternalIdentifierSearch(
        identifier=identifier,
        identifier_type=identifier_type,
        other_identifier_name=other_identifier_name,
    )
    reference = await reference_service.get_reference_from_identifier(
        external_identifier
    )
    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference with identifier {external_identifier} not found.",
        )
    return reference


@router.post("/", status_code=status.HTTP_201_CREATED)
async def register_reference(
    reference_service: Annotated[ReferenceService, Depends(import_service)],
) -> Reference:
    """Create a record for an import process."""
    return await reference_service.register_reference()


@router.post("/{reference_id}/identifier/", status_code=status.HTTP_201_CREATED)
async def add_identifier(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(import_service)],
    external_identifier: ExternalIdentifierCreate,
) -> ExternalIdentifier:
    """Create a record for an import process."""
    return await reference_service.add_identifier(reference_id, external_identifier)


@router.post("/{reference_id}/enhancement/", status_code=status.HTTP_201_CREATED)
async def add_enhancement(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(import_service)],
    enhancement: EnhancementCreate,
) -> Enhancement:
    """Create a record for an import process."""
    return await reference_service.add_enhancement(reference_id, enhancement)
