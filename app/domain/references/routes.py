"""Router for handling management of references."""

import uuid
from typing import Annotated

import destiny_sdk
from destiny_sdk.auth import CachingStrategyAuth
from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierSearch,
)
from app.domain.references.reference_service import ReferenceService
from app.domain.references.tasks import (
    collect_and_dispatch_references_for_batch_enhancement,
    validate_and_import_batch_enhancement_result,
)
from app.domain.robots.models import Robots
from app.domain.robots.service import RobotService
from app.persistence.blob.service import get_signed_url
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger()


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


def robot_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
    robots: Annotated[Robots, Depends(robots)],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(sql_uow=sql_uow, robots=robots)


def enhancement_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(unit_of_work)],
) -> EnhancementService:
    """Return the enhancement service using the provided unit of work dependencies."""
    return EnhancementService(sql_uow=sql_uow)


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
) -> destiny_sdk.references.Reference:
    """Get a reference by id."""
    reference = await reference_service.get_reference(reference_id)
    return reference.to_sdk()


@router.get("/", dependencies=[Depends(reference_reader_auth)])
async def get_reference_from_identifier(
    identifier: str,
    identifier_type: destiny_sdk.identifiers.ExternalIdentifierType,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    other_identifier_name: str | None = None,
) -> destiny_sdk.references.Reference:
    """Get a reference given an external identifier."""
    external_identifier = ExternalIdentifierSearch(
        identifier=identifier,
        identifier_type=identifier_type,
        other_identifier_name=other_identifier_name,
    )
    reference = await reference_service.get_reference_from_identifier(
        external_identifier
    )
    return reference.to_sdk()


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reference_writer_auth)],
)
async def register_reference(
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> destiny_sdk.references.Reference:
    """Create a reference."""
    reference = await reference_service.register_reference()
    return reference.to_sdk()


@router.post(
    "/{reference_id}/identifier/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(reference_writer_auth)],
)
async def add_identifier(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    external_identifier: destiny_sdk.identifiers.ExternalIdentifier,
) -> destiny_sdk.identifiers.LinkedExternalIdentifier:
    """Add an identifier to a reference."""
    identifier = await reference_service.add_identifier(
        reference_id, external_identifier
    )
    return identifier.to_sdk()


@router.post(
    "/enhancement/single/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_enhancement(
    enhancement_request_in: destiny_sdk.robots.EnhancementRequestIn,
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = await enhancement_service.request_reference_enhancement(
        enhancement_request=EnhancementRequest.from_sdk(enhancement_request_in),
        robot_service=robot_service,
    )

    return enhancement_request.to_sdk()


@router.post(
    "/enhancement/batch/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_batch_enhancement(
    enhancement_request_in: destiny_sdk.robots.BatchEnhancementRequestIn,
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = (
        await enhancement_service.register_batch_reference_enhancement_request(
            enhancement_request=BatchEnhancementRequest.from_sdk(
                enhancement_request_in
            ),
        )
    )

    logger.info(
        "Enqueueing enhancement batch",
        extra={"batch_enhancement_request_id": enhancement_request.id},
    )
    await collect_and_dispatch_references_for_batch_enhancement.kiq(
        batch_enhancement_request_id=enhancement_request.id,
    )
    return enhancement_request.to_sdk(get_signed_url)


@router.get(
    "/enhancement/single/request/{enhancement_request_id}/",
    dependencies=[Depends(reference_writer_auth)],
)
async def check_enhancement_request_status(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the enhancement request.")
    ],
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Check the status of an enhancement request."""
    enhancement_request = await enhancement_service.get_enhancement_request(
        enhancement_request_id
    )

    return enhancement_request.to_sdk()


@router.get(
    "/enhancement/batch/request/{batch_enhancement_request_id}/",
    dependencies=[Depends(reference_writer_auth)],
)
async def check_batch_enhancement_request_status(
    batch_enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the batch enhancement request.")
    ],
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Check the status of a batch enhancement request."""
    batch_enhancement_request = await enhancement_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    return batch_enhancement_request.to_sdk(get_signed_url)


@robot_router.post("/enhancement/single/", status_code=status.HTTP_200_OK)
async def fulfill_enhancement_request(
    robot_result: destiny_sdk.robots.RobotResult,
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Create an enhancement against an existing enhancement request."""
    if robot_result.error:
        enhancement_request = await enhancement_service.mark_enhancement_request_failed(
            enhancement_request_id=robot_result.request_id,
            error=robot_result.error.message,
        )
        return enhancement_request.to_sdk()
    if not robot_result.enhancement:
        enhancement_request = await enhancement_service.mark_enhancement_request_failed(
            enhancement_request_id=robot_result.request_id,
            error="No enhancement received.",
        )
        return enhancement_request.to_sdk()

    enhancement_request = await enhancement_service.create_reference_enhancement(
        enhancement_request_id=robot_result.request_id,
        enhancement=Enhancement.from_sdk(robot_result.enhancement),
    )

    return enhancement_request.to_sdk()


@robot_router.post(
    "/enhancement/batch/",
    status_code=status.HTTP_200_OK,
)
async def fulfill_batch_enhancement_request(
    robot_result: destiny_sdk.robots.BatchRobotResult,
    enhancement_service: Annotated[EnhancementService, Depends(enhancement_service)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Receive the robot result and kick off importing the enhancements."""
    logger.info(
        "Received batch enhancement result",
        extra={"batch_enhancement_request_id": robot_result.request_id},
    )
    if robot_result.error:
        batch_enhancement_request = (
            await enhancement_service.mark_batch_enhancement_request_failed(
                batch_enhancement_request_id=robot_result.request_id,
                error=robot_result.error.message,
            )
        )
        return batch_enhancement_request.to_sdk(get_signed_url)

    batch_enhancement_request = (
        await enhancement_service.update_batch_enhancement_request_status(
            batch_enhancement_request_id=robot_result.request_id,
            status=BatchEnhancementRequestStatus.PROCESSED,
        )
    )

    await validate_and_import_batch_enhancement_result.kiq(
        batch_enhancement_request_id=robot_result.request_id,
    )

    return batch_enhancement_request.to_sdk(get_signed_url)
