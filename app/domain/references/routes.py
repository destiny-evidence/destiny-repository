"""Router for handling management of references."""

import uuid
from typing import Annotated

from destiny_sdk.core import (
    EnhancementRequestCreate,
    EnhancementRequestRead,
    EnhancementRequestStatusRead,
)
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    CachingStrategyAuth,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    EnhancementRequest,
    ExternalIdentifier,
    ExternalIdentifierCreate,
    ExternalIdentifierSearch,
    ExternalIdentifierType,
    Reference,
)
from app.domain.references.reference_service import ReferenceService
from app.domain.robots import Robots
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


robots = Robots(known_robots=settings.known_robots)


def enhancement_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
    robots: Annotated[Robots, Depends(robots)],
) -> EnhancementService:
    """Return the enhancement service using the provided unit of work dependencies."""
    return EnhancementService(sql_uow=sql_uow, robots=robots)


def choose_auth_strategy_reader() -> AuthMethod:
    """Choose reader scope auth strategy for our authorization."""
    return choose_auth_strategy(
        environment=settings.env,
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.REFERENCE_READER,
    )


def choose_auth_strategy_writer() -> AuthMethod:
    """Choose writer scope auth strategy for our authorization."""
    return choose_auth_strategy(
        environment=settings.env,
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.REFERENCE_WRITER,
    )


def choose_auth_strategy_robot() -> AuthMethod:
    """Choose robot scope auth strategy for our authorization."""
    return choose_auth_strategy(
        environment=settings.env,
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScopes.ROBOT,
    )


reference_reader_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reader,
)

reference_writer_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_writer,
)

robot_auth = CachingStrategyAuth(selector=choose_auth_strategy_robot)

router = APIRouter(prefix="/references", tags=["references"])
robot_router = APIRouter(
    prefix="/robot", tags=["robots"], dependencies=[Depends(robot_auth)]
)


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
    "/enhancement/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_enhancement(
    enhancement_request_create: EnhancementRequestCreate,
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> EnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = await enhancement_service.request_reference_enhancement(
        enhancement_request=EnhancementRequest(
            **enhancement_request_create.model_dump()
        )
    )

    return EnhancementRequestRead(**enhancement_request.model_dump())


@router.get(
    "/enhancement/request/{enhancement_request_id}/",
    dependencies=[Depends(reference_writer_auth)],
)
async def check_enhancement_request_status(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the enhancement request.")
    ],
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> EnhancementRequestStatusRead:
    """Check the status of an enhancement request."""
    enhancement_request = await enhancement_service.get_enhancement_request(
        enhancement_request_id
    )

    return EnhancementRequestStatusRead(**enhancement_request.model_dump())
