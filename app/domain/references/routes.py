"""Router for handling management of references."""

import uuid
from typing import Annotated

import destiny_sdk
from elasticsearch import AsyncElasticsearch
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    AuthMethod,
    AuthRole,
    AuthScope,
    CachingStrategyAuth,
    HMACClientType,
    choose_auth_strategy,
    choose_hybrid_auth_strategy,
    security,
)
from app.core.config import get_settings
from app.core.telemetry.fastapi import PayloadAttributeTracer
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    EnhancementRequestStatus,
    ExternalIdentifierSearch,
    PendingEnhancementStatus,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.tasks import (
    validate_and_import_enhancement_result,
    validate_and_import_robot_enhancement_batch_result,
)
from app.domain.robots.service import RobotService
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.persistence.blob.repository import BlobRepository
from app.persistence.es.client import get_client
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork

settings = get_settings()
logger = get_logger(__name__)


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


def blob_repository() -> BlobRepository:
    """Return the blob storage service."""
    return BlobRepository()


def reference_anti_corruption_service(
    blob_repository: Annotated[BlobRepository, Depends(blob_repository)],
) -> ReferenceAntiCorruptionService:
    """Return the reference anti-corruption service."""
    return ReferenceAntiCorruptionService(blob_repository=blob_repository)


def robot_anti_corruption_service() -> RobotAntiCorruptionService:
    """Return the robot anti-corruption service."""
    return RobotAntiCorruptionService()


def reference_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
    es_uow: Annotated[AsyncESUnitOfWork, Depends(es_unit_of_work)],
    reference_anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> ReferenceService:
    """Return the reference service using the provided unit of work dependencies."""
    return ReferenceService(
        sql_uow=sql_uow,
        es_uow=es_uow,
        anti_corruption_service=reference_anti_corruption_service,
    )


def robot_service(
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
    robot_anti_corruption_service: Annotated[
        RobotAntiCorruptionService, Depends(robot_anti_corruption_service)
    ],
) -> RobotService:
    """Return the robot service using the provided unit of work dependencies."""
    return RobotService(
        sql_uow=sql_uow,
        anti_corruption_service=robot_anti_corruption_service,
    )


def choose_auth_strategy_reference_reader() -> AuthMethod:
    """Choose reader scope auth strategy for our authorization."""
    return choose_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScope.REFERENCE_READER,
        auth_role=AuthRole.REFERENCE_READER,
        bypass_auth=settings.running_locally,
    )


# NB hybrid_auth is not easily wrapped in CachingStrategyAuth because of the robot
# service dependency.
# May be revisited with https://github.com/destiny-evidence/destiny-repository/issues/199
async def enhancement_request_hybrid_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
) -> bool:
    """Choose enhancement request writer scope auth strategy for our authorization."""
    return await choose_hybrid_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        jwt_scope=AuthScope.ENHANCEMENT_REQUEST_WRITER,
        jwt_role=AuthRole.ENHANCEMENT_REQUEST_WRITER,
        get_client_secret=robot_service.get_robot_secret_standalone,
        hmac_client_type=HMACClientType.ROBOT,
        bypass_auth=settings.running_locally,
    )(request=request, credentials=credentials)


reference_reader_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reference_reader,
)


reference_router = APIRouter(
    prefix="/references",
    tags=["references"],
    dependencies=[Depends(reference_reader_auth)],
)
enhancement_request_router = APIRouter(
    prefix="/enhancement-requests",
    tags=["enhancement-requests"],
    dependencies=[
        Depends(enhancement_request_hybrid_auth),
        Depends(PayloadAttributeTracer("robot_id")),
    ],
)
robot_enhancement_batch_router = APIRouter(
    prefix="/robot-enhancement-batch",
    tags=["robot-enhancement-batch"],
    dependencies=[
        Depends(enhancement_request_hybrid_auth),
        Depends(PayloadAttributeTracer("robot_id")),
    ],
)
enhancement_request_automation_router = APIRouter(
    prefix="/automations",
    tags=["automated-enhancement-requests"],
    dependencies=[
        Depends(enhancement_request_hybrid_auth),
        Depends(PayloadAttributeTracer("robot_id")),
    ],
)


@reference_router.get("/{reference_id}/")
async def get_reference(
    reference_id: Annotated[uuid.UUID, Path(description="The ID of the reference.")],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.references.Reference:
    """Get a reference by id."""
    reference = await reference_service.get_reference(reference_id)
    return anti_corruption_service.reference_to_sdk(reference)


@reference_router.get("/")
async def get_reference_from_identifier(
    identifier: str,
    identifier_type: destiny_sdk.identifiers.ExternalIdentifierType,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
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
    return anti_corruption_service.reference_to_sdk(reference)


@enhancement_request_automation_router.post(
    path="/", status_code=status.HTTP_201_CREATED
)
async def add_robot_automation(
    robot_automation: destiny_sdk.robots.RobotAutomationIn,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.robots.RobotAutomation:
    """Add a robot automation."""
    automation = anti_corruption_service.robot_automation_from_sdk(robot_automation)
    added_automation = await reference_service.add_robot_automation(
        robot_service=robot_service, automation=automation
    )
    return anti_corruption_service.robot_automation_to_sdk(added_automation)


@enhancement_request_automation_router.put(
    path="/{automation_id}/", status_code=status.HTTP_201_CREATED
)
async def update_robot_automation(
    automation_id: Annotated[uuid.UUID, Path(description="The ID of the automation.")],
    robot_automation: destiny_sdk.robots.RobotAutomationIn,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    robot_service: Annotated[RobotService, Depends(robot_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.robots.RobotAutomation:
    """Update a robot automation."""
    automation = anti_corruption_service.robot_automation_from_sdk(
        robot_automation, automation_id=automation_id
    )
    updated_automation = await reference_service.update_robot_automation(
        automation=automation, robot_service=robot_service
    )
    return anti_corruption_service.robot_automation_to_sdk(updated_automation)


@enhancement_request_automation_router.get(path="/", status_code=status.HTTP_200_OK)
async def get_robot_automations(
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> list[destiny_sdk.robots.RobotAutomation]:
    """Get all robot automations."""
    automations = await reference_service.get_robot_automations()
    return [
        anti_corruption_service.robot_automation_to_sdk(automation)
        for automation in automations
    ]


# TODO(danielribeiro): Consider authenticating robot_id matches auth client id  # noqa: E501, TD003
@robot_enhancement_batch_router.post(
    "/",
    response_model=destiny_sdk.robots.RobotEnhancementBatch,
    summary="Request a batch of references to enhance.",
    responses={204: {"model": None}},
)
async def request_robot_enhancement_batch(
    robot_id: Annotated[
        uuid.UUID,
        Query(description="The ID of the robot."),
    ],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    blob_repository: Annotated[BlobRepository, Depends(blob_repository)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService,
        Depends(reference_anti_corruption_service),
    ],
    limit: Annotated[
        int,
        Query(
            description="The maximum number of pending enhancements to return.",
        ),
    ] = settings.max_pending_enhancements_batch_size,
) -> destiny_sdk.robots.RobotEnhancementBatch | Response:
    """
    Request a batch of references to enhance.

    This endpoint is used by robots to poll for new enhancement requests.
    """
    if limit > settings.max_pending_enhancements_batch_size:
        limit = settings.max_pending_enhancements_batch_size
        logger.warning(
            "Pending enhancements limit exceeded. "
            "Using max_pending_enhancements_batch_size: %d",
            limit,
        )

    pending_enhancements = await reference_service.get_pending_enhancements_for_robot(
        robot_id=robot_id,
        limit=limit,
    )
    if not pending_enhancements:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    robot_enhancement_batch = await reference_service.create_robot_enhancement_batch(
        robot_id=robot_id,
        pending_enhancements=pending_enhancements,
        blob_repository=blob_repository,
    )

    return await anti_corruption_service.robot_enhancement_batch_to_sdk_robot(
        robot_enhancement_batch
    )

@robot_enhancement_batch_router.get(
    "/{robot_enhancement_batch_id}/",
    response_model=destiny_sdk.robots.RobotEnhancementBatch,
    summary="Get an existing batch of references to enhance"
)
async def get_robot_enhancement_batch(
    robot_enhancement_batch_id: uuid.UUID,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService,
        Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.robots.RobotEnhancementBatch:
    """
    Request an existing batch of references to enhance.

    This endpoint is used by robots to refresh signed urls on enhancement batches.
    """
    robot_enhancement_batch = await reference_service.get_robot_enhancement_batch(
        robot_enhancement_batch_id
    )
    return await anti_corruption_service.robot_enhancement_batch_to_sdk_robot(
        robot_enhancement_batch
    )

enhancement_request_router.include_router(enhancement_request_automation_router)


@enhancement_request_router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_enhancement(
    enhancement_request_in: destiny_sdk.robots.EnhancementRequestIn,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Request the creation of an enhancement against a provided reference id."""
    enhancement_request = (
        await reference_service.register_reference_enhancement_request(
            enhancement_request=anti_corruption_service.enhancement_request_from_sdk(
                enhancement_request_in
            ),
        )
    )

    return await anti_corruption_service.enhancement_request_to_sdk(enhancement_request)


@enhancement_request_router.get(
    "/{enhancement_request_id}/",
)
async def check_enhancement_request_status(
    enhancement_request_id: Annotated[
        uuid.UUID, Path(description="The ID of the batch enhancement request.")
    ],
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Check the status of a batch enhancement request."""
    enhancement_request = (
        await reference_service.get_enhancement_request_with_calculated_status(
            enhancement_request_id
        )
    )

    return await anti_corruption_service.enhancement_request_to_sdk(enhancement_request)


@enhancement_request_router.post(
    "/{enhancement_request_id}/results/",
    status_code=status.HTTP_202_ACCEPTED,
)
@enhancement_request_router.post(
    "/batch-requests/{enhancement_request_id}/results/",
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
)
async def fulfill_enhancement_request(
    robot_result: destiny_sdk.robots.RobotResult,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    response: Response,
) -> destiny_sdk.robots.EnhancementRequestRead:
    """Receive the robot result and kick off importing the enhancements."""
    if robot_result.error:
        enhancement_request = await reference_service.mark_enhancement_request_failed(
            enhancement_request_id=robot_result.request_id,
            error=robot_result.error.message,
        )
        response.status_code = status.HTTP_200_OK
        return await anti_corruption_service.enhancement_request_to_sdk(
            enhancement_request
        )

    enhancement_request = await reference_service.update_enhancement_request_status(
        enhancement_request_id=robot_result.request_id,
        status=EnhancementRequestStatus.IMPORTING,
    )

    await queue_task_with_trace(
        validate_and_import_enhancement_result,
        enhancement_request_id=robot_result.request_id,
    )

    return await anti_corruption_service.enhancement_request_to_sdk(enhancement_request)


@robot_enhancement_batch_router.post(
    "/{robot_enhancement_batch_id}/results/",
    status_code=status.HTTP_202_ACCEPTED,
)
async def fulfill_robot_enhancement_batch(
    robot_enhancement_batch_id: Annotated[
        uuid.UUID,
        Path(description="The ID of the robot enhancement batch."),
    ],
    robot_result: destiny_sdk.robots.RobotEnhancementBatchResult,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    response: Response,
) -> destiny_sdk.robots.RobotEnhancementBatchRead:
    """Receive the robot result and kick off importing the enhancements."""
    if robot_result.request_id != robot_enhancement_batch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request ID mismatch"
        )

    if robot_result.error:
        robot_enhancement_batch = (
            await reference_service.mark_robot_enhancement_batch_failed(
                robot_enhancement_batch_id=robot_enhancement_batch_id,
                error=robot_result.error.message,
            )
        )

        response.status_code = status.HTTP_200_OK
        return await anti_corruption_service.robot_enhancement_batch_to_sdk(
            robot_enhancement_batch
        )

    robot_enhancement_batch = await reference_service.get_robot_enhancement_batch(
        robot_enhancement_batch_id
    )

    await reference_service.update_pending_enhancements_status_for_robot_enhancement_batch(  # noqa: E501
        robot_enhancement_batch_id=robot_enhancement_batch.id,
        status=PendingEnhancementStatus.IMPORTING,
    )

    await queue_task_with_trace(
        validate_and_import_robot_enhancement_batch_result,
        robot_enhancement_batch_id=robot_enhancement_batch_id,
    )

    return await anti_corruption_service.robot_enhancement_batch_to_sdk(
        robot_enhancement_batch
    )
