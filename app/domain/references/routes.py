# Typing transgressions here make the API docs cleaner. Sorry.
# For optional parameters, the preferred Python method is to type it optionally
# eg list[str] | None = None, but in the docs this forks the parameter to also
# show `null` as an option, which is not desired and obscures the actual usage.
#
# mypy: disable-error-code="assignment"
# ruff: noqa: RUF013

"""Router for handling management of references."""

import datetime
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
from pydantic import BaseModel, Field, field_validator
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
from app.api.decorators import experimental
from app.api.exception_handlers import APIExceptionContent, APIExceptionResponse
from app.core.config import get_settings
from app.core.exceptions import ParseError, StateTransitionError
from app.core.telemetry.fastapi import PayloadAttributeTracer
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.models import (
    AnnotationFilter,
    PendingEnhancementStatus,
    PublicationYearRange,
    ReferenceIds,
)
from app.domain.references.service import ReferenceService
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.references.services.search_service import SearchService
from app.domain.references.tasks import (
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
from app.utils.time_and_date import utc_now

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
        bypass_auth=settings.should_bypass_auth,
    )


def choose_auth_strategy_reference_deduplicator() -> AuthMethod:
    """Choose reader scope auth strategy for our authorization."""
    return choose_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScope.REFERENCE_DEDUPLICATOR,
        auth_role=AuthRole.REFERENCE_DEDUPLICATOR,
        bypass_auth=settings.should_bypass_auth,
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
        bypass_auth=settings.should_bypass_auth,
    )(request=request, credentials=credentials)


reference_reader_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reference_reader,
)
reference_deduplication_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_reference_deduplicator,
)


reference_router = APIRouter(
    prefix="/references",
    tags=["references"],
    dependencies=[Depends(reference_reader_auth)],
)
search_router = APIRouter(
    prefix="/search",
    tags=["search"],
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
    prefix="/robot-enhancement-batches",
    tags=["robot-enhancement-batches"],
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
deduplication_router = APIRouter(
    prefix="/duplicate-decisions",
    tags=["duplicate-decisions"],
    dependencies=[Depends(reference_deduplication_auth)],
)


def parse_publication_year_range(
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    start_year: Annotated[
        int,
        Query(description="Filter for references published on or after this year."),
    ] = None,
    end_year: Annotated[
        int,
        Query(description="Filter for references published on or before this year."),
    ] = None,
) -> PublicationYearRange | None:
    """Parse a publication year range from a query parameter."""
    if start_year or end_year:
        return anti_corruption_service.publication_year_range_from_query_parameter(
            start_year, end_year
        )
    return None


def parse_annotation_filters(
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    annotation: Annotated[
        list[str],
        Query(
            description=(
                "A list of annotation filters to apply to the search.\n\n"
                "- If an annotation is provided without a score, "
                "results will be filtered for that annotation being true.\n"
                "- If a score is specified, "
                "results will be filtered for that annotation having a score "
                "greater than or equal to the given value.\n"
                "- If the label is omitted, results will be filtered if any "
                "annotation with the given scheme is true.\n"
                "- Multiple annotations are combined using AND logic.\n\n"
                "Format: `<scheme>[/<label>][@<score>]`. "
            ),
            examples=[
                "inclusion:destiny@0.8",
                "classifier:taxonomy:Outcomes/Influenza",
            ],
        ),
    ] = None,
) -> list[AnnotationFilter]:
    """Parse annotation filters from query parameters."""
    if not annotation:
        return []
    return [
        anti_corruption_service.annotation_filter_from_query_parameter(
            annotation_filter_string
        )
        for annotation_filter_string in annotation
    ]


@search_router.get(
    "/",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Bad Query String",
            "model": APIExceptionContent,
        }
    },
    description="Search for references using a query string in "
    "[Lucene syntax](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query#query-string-syntax)"
    ". If the query string does not specify search fields, the search will query over "
    f"[{', '.join(SearchService.default_search_fields)}]. The query string can only "
    "search over fields on the root level of the Reference document.\n\n"
    "A natural limit of 10,000 results is imposed. You cannot page beyond this limit, "
    "and if a query would return more than 10,000 results the total count is listed as "
    ">10,000.",
)
async def search_references(
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    q: Annotated[
        str,
        Query(
            description="The query string.",
        ),
    ],
    annotations: Annotated[
        list[AnnotationFilter] | None,
        Depends(parse_annotation_filters),
    ],
    publication_year_range: Annotated[
        PublicationYearRange | None,
        Depends(parse_publication_year_range),
    ],
    page: Annotated[
        int,
        Query(
            ge=1,
            le=10_000 / 20,  # Elasticsearch max result window divided by page size
            description="The page number to retrieve, indexed from 1. "
            "Each page contains 20 results.",
        ),
    ] = 1,
    sort: Annotated[
        list[str],
        Query(
            description="A list of fields to sort the results by. "
            "Prefix a field with `-` to sort in descending order. "
            "If omitted, will sort by relevance score descending. "
            "Multiple sort fields can be provided and will be applied "
            "in the order given. Sort fields cannot be `text` fields.",
        ),
    ] = None,
) -> destiny_sdk.references.ReferenceSearchResult:
    """Search for references given a query string."""
    search_result = await reference_service.search_references(
        q,
        page=page,
        annotations=annotations,
        publication_year_range=publication_year_range,
        sort=sort,
    )
    return anti_corruption_service.reference_search_result_to_sdk(search_result)


# NB it's important this occurs before defining `/references/{reference_id}/` route
# to avoid route conflicts. Order matters for FastAPI route matching.
reference_router.include_router(search_router)


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


class IdentifierLookupQueryParams(BaseModel):
    """Query parameters for looking up references by identifiers."""

    identifier: list[str] = Field(
        ...,
        description=(
            "A list of external identifier lookups. "
            "Can be provided in multiple query parameters or as a single "
            "csv string."
        ),
        examples=[
            "02e376ee-8374-4a8c-997f-9a813bc5b8f8",
            "doi:10.1000/abc123",
            "other:isbn:978-1-234-56789-0",
            "pm_id:123456,open_alex:W98765",
        ],
        max_length=settings.max_lookup_reference_query_length,
    )

    @field_validator("identifier", mode="before")
    @classmethod
    def parse_csv_validator(cls, v: list[str]) -> list[str]:
        """Parse a csv string to a list if given."""
        if len(v) == 1:
            return v[0].split(",")
        return v


def parse_identifiers(
    identifier_query: Annotated[IdentifierLookupQueryParams, Query()],
) -> list[destiny_sdk.identifiers.IdentifierLookup]:
    """Parse a list of identifier lookup strings into IdentifierLookup objects."""
    try:
        return [
            destiny_sdk.identifiers.IdentifierLookup.parse(identifier_string)
            for identifier_string in identifier_query.identifier
        ]
    except ValueError as exc:
        raise ParseError(detail=str(exc)) from exc


@reference_router.get("/")
@experimental
async def lookup_references(
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
    ],
    identifiers: Annotated[
        list[destiny_sdk.identifiers.IdentifierLookup], Depends(parse_identifiers)
    ],
) -> list[destiny_sdk.references.Reference]:
    """Get references given identifiers."""
    identifier_lookups = anti_corruption_service.identifier_lookups_from_sdk(
        identifiers
    )
    return [
        anti_corruption_service.reference_to_sdk(reference)
        for reference in await reference_service.get_references_from_identifiers(
            identifier_lookups
        )
    ]


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
    lease: Annotated[
        datetime.timedelta,
        Query(
            description="The duration to lease the pending enhancements for, "
            "provided in ISO 8601 duration format.",
        ),
    ] = settings.default_pending_enhancement_lease_duration,
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
        lease_duration=lease,
        blob_repository=blob_repository,
    )

    return await anti_corruption_service.robot_enhancement_batch_to_sdk_robot(
        robot_enhancement_batch
    )


@robot_enhancement_batch_router.patch(
    "/{robot_enhancement_batch_id}/renew-lease/",
    response_model=Annotated[
        str,
        Field(
            description="The new lease expiry timestamp.",
            examples=[utc_now().isoformat()],
        ),
    ],
    summary="Renew the lease on an existing batch of references to enhance",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": Annotated[
                APIExceptionContent,
                Field(
                    examples=[
                        {
                            "detail": (
                                conflict_msg
                                := "This batch has no pending enhancements. "
                                "They may have already expired or been completed."
                            )
                        }
                    ]
                ),
            ]
        }
    },
)
async def renew_robot_enhancement_batch_lease(
    robot_enhancement_batch_id: uuid.UUID,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    lease: Annotated[
        datetime.timedelta,
        Query(
            description="The duration to lease the pending enhancements for, "
            "provided in ISO 8601 duration format."
        ),
    ] = settings.default_pending_enhancement_lease_duration,
) -> Response:
    """
    Renew the lease on an existing batch of references to enhance.

    This endpoint is used by robots to extend the lease on enhancement batches.
    """
    updated, expiry = await reference_service.renew_robot_enhancement_batch_lease(
        robot_enhancement_batch_id=robot_enhancement_batch_id,
        lease_duration=lease,
    )
    if not updated:
        return APIExceptionResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=APIExceptionContent(detail=conflict_msg),
        )
    return Response(
        content=expiry.isoformat(),
        status_code=status.HTTP_200_OK,
    )


@robot_enhancement_batch_router.get(
    "/{robot_enhancement_batch_id}/",
    response_model=destiny_sdk.robots.RobotEnhancementBatch,
    summary="Get an existing batch of references to enhance",
)
async def get_robot_enhancement_batch(
    robot_enhancement_batch_id: uuid.UUID,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
    anti_corruption_service: Annotated[
        ReferenceAntiCorruptionService, Depends(reference_anti_corruption_service)
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

    try:
        await reference_service.update_pending_enhancements_status_for_robot_enhancement_batch(  # noqa: E501
            robot_enhancement_batch_id=robot_enhancement_batch.id,
            status=PendingEnhancementStatus.IMPORTING,
        )
    except StateTransitionError as e:
        logger.warning(
            "Failed to start importing robot enhancement batch results.",
            robot_enhancement_batch_id=str(robot_enhancement_batch_id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot process results: {e}",
        ) from e

    await queue_task_with_trace(
        validate_and_import_robot_enhancement_batch_result,
        long_running=True,
        robot_enhancement_batch_id=robot_enhancement_batch_id,
        otel_enabled=settings.otel_enabled,
    )

    return await anti_corruption_service.robot_enhancement_batch_to_sdk(
        robot_enhancement_batch
    )


@deduplication_router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
)
async def invoke_deduplication_for_references(
    reference_ids: ReferenceIds,
    reference_service: Annotated[ReferenceService, Depends(reference_service)],
) -> None:
    """Invoke the deduplication process."""
    logger.info(
        "Invoking deduplication for references.",
        n_references=len(reference_ids.reference_ids),
    )
    await reference_service.invoke_deduplication_for_references(reference_ids)


reference_router.include_router(deduplication_router)
