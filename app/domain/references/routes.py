"""Router for handling management of references."""

import uuid
from typing import Annotated

import destiny_sdk
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthMethod,
    AuthScopes,
    CachingStrategyAuth,
    choose_auth_strategy,
    choose_hmac_auth_strategy,
)
from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Enhancement,
    EnhancementRequest,
    ExternalIdentifierSearch,
    RobotAutomation,
)
from app.domain.references.service import ReferenceService
from app.domain.references.tasks import (
    collect_and_dispatch_references_for_batch_enhancement,
    rebuild_reference_index,
    validate_and_import_batch_enhancement_result,
)
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.client import get_client
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger()


def sql_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return the unit of work for operating on references."""
    return AsyncSqlUnitOfWork(session=session)


def es_unit_of_work(
    client: Annotated[AsyncElasticsearch, Depends(get_client)],
) -> AsyncESUnitOfWork:
    """Return the unit of work for operating on references in Elasticsearch."""
    return AsyncESUnitOfWork(client=client)


def reference_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
    es_uow: Annotated[AsyncESUnitOfWork, Depends(es_unit_of_work)],
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    return ReferenceService(sql_uow=sql_uow, es_uow=es_uow)


def robot_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(sql_uow=sql_uow)


def robot_request_dispatcher() -> RobotRequestDispatcher:
    """Return the robot request dispatcher."""
    return RobotRequestDispatcher()


def blob_repository() -> BlobRepository:
    """Return the blob storage service."""
    return BlobRepository()


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


reference_reader_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reader,
)

reference_writer_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_writer,
)


async def robot_auth(
    request: Request,
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> bool:
    """Choose robot auth strategy for our authorization."""
    return await choose_hmac_auth_strategy(
        get_client_secret=robot_service.get_robot_secret_standalone,
    )(request)


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
    return await reference.to_sdk()


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
    return await reference.to_sdk()


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
    return await reference.to_sdk()


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
    return await identifier.to_sdk()


@router.post(
    "/enhancement/single/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_enhancement(
    enhancement_request_in: destiny_sdk.robots.EnhancementRequestIn,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
    robot_request_dispatcher: Annotated[
        RobotRequestDispatcher, Depends(robot_request_dispatcher)
    ],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = await reference_service.request_reference_enhancement(
        enhancement_request=await EnhancementRequest.from_sdk(enhancement_request_in),
        robot_service=robot_service,
        robot_request_dispatcher=robot_request_dispatcher,
    )

    return await enhancement_request.to_sdk()


@router.post(
    "/enhancement/batch/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reference_writer_auth)],
)
async def request_batch_enhancement(
    enhancement_request_in: destiny_sdk.robots.BatchEnhancementRequestIn,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    blob_repository: Annotated[BlobRepository, Depends(blob_repository)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = (
        await reference_service.register_batch_reference_enhancement_request(
            enhancement_request=await BatchEnhancementRequest.from_sdk(
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
    return await enhancement_request.to_sdk(blob_repository.get_signed_url)


@router.get(
    "/enhancement/single/request/{enhancement_request_id}/",
    dependencies=[Depends(reference_writer_auth)],
)
async def check_enhancement_request_status(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the enhancement request.")
    ],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Check the status of an enhancement request."""
    enhancement_request = await reference_service.get_enhancement_request(
        enhancement_request_id
    )

    return await enhancement_request.to_sdk()


@router.get(
    "/enhancement/batch/request/{batch_enhancement_request_id}/",
    dependencies=[Depends(reference_writer_auth)],
)
async def check_batch_enhancement_request_status(
    batch_enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the batch enhancement request.")
    ],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    blob_repository: Annotated[BlobRepository, Depends(blob_repository)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Check the status of a batch enhancement request."""
    batch_enhancement_request = await reference_service.get_batch_enhancement_request(
        batch_enhancement_request_id
    )

    return await batch_enhancement_request.to_sdk(blob_repository.get_signed_url)


@router.post("/index/rebuild/")
async def rebuild_index() -> None:
    """Delete, recreate and repopulate the Elasticsearch index."""
    await rebuild_reference_index.kiq()


@robot_router.post("/enhancement/single/", status_code=status.HTTP_200_OK)
async def fulfill_enhancement_request(
    robot_result: destiny_sdk.robots.RobotResult,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Create an enhancement against an existing enhancement request."""
    if robot_result.error:
        enhancement_request = await reference_service.mark_enhancement_request_failed(
            enhancement_request_id=robot_result.request_id,
            error=robot_result.error.message,
        )
        return await enhancement_request.to_sdk()
    if not robot_result.enhancement:
        enhancement_request = await reference_service.mark_enhancement_request_failed(
            enhancement_request_id=robot_result.request_id,
            error="No enhancement received.",
        )
        return await enhancement_request.to_sdk()

    enhancement_request = (
        await reference_service.create_reference_enhancement_from_request(
            enhancement_request_id=robot_result.request_id,
            enhancement=await Enhancement.from_sdk(robot_result.enhancement),
        )
    )

    return await enhancement_request.to_sdk()


@robot_router.post(
    "/enhancement/batch/",
    status_code=status.HTTP_200_OK,
)
async def fulfill_batch_enhancement_request(
    robot_result: destiny_sdk.robots.BatchRobotResult,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    blob_repository: Annotated[BlobRepository, Depends(blob_repository)],
) -> destiny_sdk.robots.BatchEnhancementRequestRead:
    """Receive the robot result and kick off importing the enhancements."""
    logger.info(
        "Received batch enhancement result",
        extra={"batch_enhancement_request_id": robot_result.request_id},
    )
    if robot_result.error:
        batch_enhancement_request = (
            await reference_service.mark_batch_enhancement_request_failed(
                batch_enhancement_request_id=robot_result.request_id,
                error=robot_result.error.message,
            )
        )
        return await batch_enhancement_request.to_sdk(blob_repository.get_signed_url)

    batch_enhancement_request = (
        await reference_service.update_batch_enhancement_request_status(
            batch_enhancement_request_id=robot_result.request_id,
            status=BatchEnhancementRequestStatus.IMPORTING,
        )
    )

    await validate_and_import_batch_enhancement_result.kiq(
        batch_enhancement_request_id=robot_result.request_id,
    )

    return await batch_enhancement_request.to_sdk(blob_repository.get_signed_url)


@robot_router.post(path="/automation/", status_code=status.HTTP_201_CREATED)
async def add_robot_automation(
    robot_automation: destiny_sdk.robots.RobotAutomation,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> destiny_sdk.robots.RobotAutomation:
    """Add a robot automation."""
    automation = await RobotAutomation.from_sdk(robot_automation)
    added_automation = await reference_service.add_robot_automation(
        robot_service=robot_service, automation=automation
    )
    return await added_automation.to_sdk()
