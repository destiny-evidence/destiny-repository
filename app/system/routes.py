"""Router for system utility endpoints."""

from typing import Annotated
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    AuthMethod,
    AuthRole,
    AuthScope,
    CachingStrategyAuth,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.core.exceptions import ESNotFoundError, InvalidPayloadError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.tasks import (
    repair_reference_index,
    repair_reference_index_subset,
    repair_robot_automation_percolation_index,
)
from app.persistence.es.client import get_client
from app.persistence.es.index_manager import IndexManager
from app.persistence.sql.session import get_session
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.system.healthcheck import HealthCheckOptions, healthcheck

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/system", tags=["system utilities"])


def reference_index_manager(es_client: AsyncElasticsearch) -> IndexManager:
    """Create an index manager for the reference index."""
    return IndexManager(
        document_class=ReferenceDocument,
        repair_task=repair_reference_index,
        repair_subset_task=repair_reference_index_subset,
        client=es_client,
        otel_enabled=settings.otel_enabled,
    )


def robot_automation_percolation_index_manager(
    es_client: AsyncElasticsearch,
) -> IndexManager:
    """Create an index manager for the robot automation percolation index."""
    return IndexManager(
        document_class=RobotAutomationPercolationDocument,
        repair_task=repair_robot_automation_percolation_index,
        client=es_client,
        otel_enabled=settings.otel_enabled,
    )


index_managers = {
    ReferenceDocument.Index.name: reference_index_manager,
    RobotAutomationPercolationDocument.Index.name: robot_automation_percolation_index_manager,  # noqa: E501
}


def get_index_manager(
    alias: Annotated[str, Path(..., description="The alias of the index to repair")],
    es_client: Annotated[AsyncElasticsearch, Depends(get_client)],
) -> IndexManager:
    """Get an index manager for a given alias."""
    try:
        return index_managers[alias](es_client)
    except KeyError as exc:
        raise ESNotFoundError(
            detail=f"Index {alias} not found.",
            lookup_model="meta:index",
            lookup_value=alias,
            lookup_type="alias",
        ) from exc


def sql_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncSqlUnitOfWork:
    """Return a SQL unit of work for system operations."""
    return AsyncSqlUnitOfWork(session=session)


def choose_auth_strategy_administrator() -> AuthMethod:
    """Choose administrator for our authorization strategy."""
    return choose_auth_strategy(
        application_id=settings.azure_application_id,
        auth_scope=AuthScope.ADMINISTRATOR,
        auth_role=AuthRole.ADMINISTRATOR,
        bypass_auth=settings.should_bypass_auth,
    )


system_utility_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_administrator,
)


@router.get("/ping/", status_code=status.HTTP_200_OK)
async def get_ping() -> JSONResponse:
    """Cheap liveness probe."""
    return JSONResponse(content={"status": "ok"})


@router.get("/healthcheck/", status_code=status.HTTP_200_OK)
async def get_healthcheck(
    healthcheck_options: Annotated[HealthCheckOptions, Depends()],
    db_session: Annotated[AsyncSession, Depends(get_session)],
    es_client: Annotated[AsyncElasticsearch, Depends(get_client)],
) -> JSONResponse:
    """Verify we are able to connect to auxiliary services."""
    result = await healthcheck(db_session, es_client, healthcheck_options)
    if result:
        raise HTTPException(status_code=500, detail=result)
    return JSONResponse(content={"status": "ok"})


@router.post(
    "/indices/{alias}/repair/",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(system_utility_auth)],
)
async def repair_elasticsearch_index(
    *,
    rebuild: Annotated[
        bool,
        Query(
            description="If true, the index will be destroyed and rebuilt before being "
            "repaired. This involves downtime but is generally useful for updating "
            "index mappings or persisting a bulk delete at the SQL level. Cannot be "
            "combined with repair_all or document_ids.",
        ),
    ] = False,
    repair_all: Annotated[
        bool,
        Query(
            description="If true, every document in the index will be re-indexed in "
            "place from its SQL counterpart, with no downtime. Removed SQL documents "
            "will NOT be removed from the index (use rebuild for that). Cannot be "
            "combined with rebuild or document_ids.",
        ),
    ] = False,
    document_ids: Annotated[
        list[UUID] | None,
        Body(
            embed=True,
            min_length=1,
            max_length=settings.es_reference_repair_max_batch_size,
            title="Document IDs to repair",
            description=(
                "If provided, only the documents with these IDs will be repaired. "
                "Cannot be combined with rebuild or repair_all."
            ),
            examples=[
                [
                    UUID("01935f56-2c8e-7000-8000-000000000001"),
                    UUID("01935f56-2c8e-7000-8000-000000000002"),
                ],
            ],
        ),
    ] = None,
    sql_uow: Annotated[AsyncSqlUnitOfWork, Depends(sql_unit_of_work)],
    index_manager: Annotated[IndexManager, Depends(get_index_manager)],
) -> JSONResponse:
    """Repair an index (update all documents per their SQL counterparts)."""
    actions_selected = sum((rebuild, repair_all, document_ids is not None))
    if actions_selected != 1:
        raise InvalidPayloadError(
            detail=(
                "Exactly one of rebuild=true, repair_all=true, or document_ids "
                "must be provided."
            ),
        )

    if document_ids is not None and index_manager.repair_subset_task is None:
        raise InvalidPayloadError(
            detail=(
                f"Subset repair is not supported for index "
                f"{index_manager.alias_name}."
            ),
        )

    if document_ids is not None:
        if index_manager.alias_name == ReferenceDocument.Index.name:
            # Reach directly into the SQL repo to fail fast on missing IDs; the
            # full ReferenceService is heavy to construct for a one-line check.
            async with sql_uow:
                await sql_uow.references.verify_pk_existence(document_ids)
        await index_manager.repair_index(document_ids=document_ids)
        message = (
            f"Subset repair task for {len(document_ids)} document(s) in index "
            f"{index_manager.alias_name} has been initiated."
        )
    elif rebuild:
        await index_manager.rebuild_index()
        message = (
            f"Repair task for index {index_manager.alias_name} has been initiated."
        )
    else:
        await index_manager.repair_index()
        message = (
            f"Repair task for index {index_manager.alias_name} has been initiated."
        )

    return JSONResponse(
        content={
            "status": "ok",
            "message": message,
        },
        status_code=status.HTTP_202_ACCEPTED,
    )
