"""Router for handling management of references."""

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
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierSearch,
    ExternalIdentifierType,
    Reference,
)
from app.domain.references.robot_service import RobotService
from app.domain.references.service import ReferenceService
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()


def unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on references."""
    return AsyncSqlUnitOfWork(session=session)


def reference_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    return ReferenceService(sql_uow=sql_uow)

def robot_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(sql_uow=sql_uow)


def choose_auth_strategy(auth_scope: AuthScopes) -> AuthMethod:
    """Choose a strategy for our authorization."""
    if settings.env in ("dev", "test"):
        return SuccessAuth()

    return AzureJwtAuth(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        scope=auth_scope,
    )


def choose_auth_strategy_reader() -> AuthMethod:
    """Choose reader scope auth strategy for our authorization."""
    return choose_auth_strategy(AuthScopes.REFERENCE_READER)


def choose_auth_strategy_writer() -> AuthMethod:
    """Choose writer scope auth strategy for our authorization."""
    return choose_auth_strategy(AuthScopes.REFERENCE_WRITER)


reference_reader_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reader,
)

reference_writer_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_writer,
)


router = APIRouter(prefix="/references", tags=["references"])


@router.get("/{reference_id}/", dependencies=[Depends(reference_reader_auth)])
async def get_reference(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> Reference:
    """Get a reference by id."""
    reference = await reference_service.get_reference(reference_id)
    if not reference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference with id {reference_id} not found.",
        )
    return reference


@router.get("/", dependencies=[Depends(reference_reader_auth)])
async def get_reference_from_identifier(
    identifier: str,
    identifier_type: ExternalIdentifierType,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    other_identifier_name: str | None = None,
) -> Reference:
    """Get a reference given an external identifier."""
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


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reference_writer_auth)],
)
async def register_reference(
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> Reference:
    """Create a reference."""
    return await reference_service.register_reference()


@router.post(
    "/{reference_id}/identifier/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reference_writer_auth)],
)
async def add_identifier(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    external_identifier: ExternalIdentifierCreate,
) -> ExternalIdentifier:
    """Add an identifier to a reference."""
    return await reference_service.add_identifier(reference_id, external_identifier)


@router.post(
    "/{reference_id}/enhancement/request",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_enhancement(
    reference_id: Annotated[
        uuid.UUID, Path(description="The ID of the reference to enhance.")
    ],
    enhancement_type: EnhancementType,
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> EnhancementRequest:
    """Request the creation of an enhancement against a provided reference id."""
    return await robot_service.request_reference_enhancement(
        reference_id, enhancement_type
    )


# Thought - do we want these to have the references prefix on them?
# Currently references/enhancement/request/{enhancement_request_id}
# Thinking like /enhancement/request/{request_id} as total path might be nicer
# I don't even think the /request/ is very nice, maybe references/enhance?
@router.patch(
    "/enhancement/request/{enhancement_request_id}/", status_code=status.HTTP_200_OK
)
async def update_enhancement_request(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The id of the enhancement request")
    ],
    enhancement_request_status: EnhancementRequestStatus,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> EnhancementRequest:
    """Update the status of an enhancement request."""
    # Allow an error to be passed in here
    # And move the enhancement request into failed state?
    # For example if we pass a malformed request to robot


@router.get(
    "/enhancement/request/{enhancement_request_id}/", status_code=status.HTTP_200_OK
)
async def check_enhancement_request_status(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The id of the enhancement request")
    ],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> EnhancementRequest:
    """Check the status of an enhancement request."""
    # For nosy users who what to see what's goin' on


@router.post("{reference_id}/enhancement/", status_code=status.HTTP_201_CREATED)
async def create_enhancement(
    reference_id: Annotated[uuid.UUID, Path(description="reference")],
    # whatever we need to create the enhancement
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> Enhancement:
    """
    Robots hit this to create an enhancement after processing an enhancement request.

    Might want to extend this to create enhancements without associated request.
    """
    # add an extra request state for 'finalizing'? felt like extra complexity
    # Create the enhancement
    # Update the enhancement request to either completed or failed.
    # Return enhancement


@router.get("/enhancement/{enhancement_id}", status_code=status.HTTP_200_OK)
async def get_enhancement(
    enhancement_id: Annotated[uuid.UUID, Path(description="The ID of an enhancement")],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> Enhancement:
    """Grab an existing enhancement by enhancement id."""
    # Will likely want to allow grabbing by type for a reference
    # Maybe 'references/{reference_id}/enhancement/{type}'
