"""Router for system utility endpoints."""

from collections.abc import Coroutine
from typing import Annotated, Any

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import AsyncTaskiqDecoratedTask

from app.api.auth import (
    AuthMethod,
    AuthRole,
    AuthScope,
    CachingStrategyAuth,
    choose_auth_strategy,
)
from app.core.config import get_settings
from app.core.exceptions import ESNotFoundError
from app.core.telemetry.logger import get_logger
from app.core.telemetry.taskiq import queue_task_with_trace
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.tasks import (
    repair_reference_index,
    repair_robot_automation_percolation_index,
)
from app.persistence.es.client import get_client
from app.persistence.es.migration import IndexManager
from app.persistence.es.persistence import GenericESPersistence
from app.persistence.sql.session import get_session
from app.system.healthcheck import HealthCheckOptions, healthcheck

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/system", tags=["system utilities"])

# Registry of repairable indices
_indices: dict[
    str,
    tuple[
        type[GenericESPersistence],
        AsyncTaskiqDecoratedTask[..., Coroutine[Any, Any, None]],
    ],
] = {
    ReferenceDocument.Index.name: (ReferenceDocument, repair_reference_index),
    RobotAutomationPercolationDocument.Index.name: (
        RobotAutomationPercolationDocument,
        repair_robot_automation_percolation_index,
    ),
}


def choose_auth_strategy_administrator() -> AuthMethod:
    """Choose administrator for our authorization strategy."""
    return choose_auth_strategy(
        tenant_id=settings.azure_tenant_id,
        application_id=settings.azure_application_id,
        auth_scope=AuthScope.ADMINISTRATOR,
        auth_role=AuthRole.ADMINISTRATOR,
        bypass_auth=settings.running_locally,
    )


system_utility_auth = CachingStrategyAuth(
    selector=choose_auth_strategy_administrator,
)


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
    es_client: Annotated[AsyncElasticsearch, Depends(get_client)],
    alias: Annotated[str, Path(..., description="The alias of the index to repair")],
    *,
    service: Annotated[
        str,
        Query(description="Service name for the persistence implementation."),
    ] = "elastic",
    rebuild: Annotated[
        bool,
        Query(
            description="If true, the index will be destroyed and rebuilt before being "
            "repaired. This involves downtime but is generally useful for updating "
            "index mappings or persisting a bulk delete at the SQL level. If false, "
            "the existing index will be updated in place without downtime, but removed"
            " documents in SQL will not be removed from the index.",
        ),
    ] = False,
) -> JSONResponse:
    """Repair an index (update all documents per their SQL counterparts)."""
    if service != "elastic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only 'elastic' service is supported for index repair.",
        )

    # If we add another persistence service, move this to a function.
    try:
        index, repair_task = _indices[alias]
    except KeyError as exc:
        raise ESNotFoundError(
            detail=f"Index {alias} not found.",
            lookup_model="meta:index",
            lookup_value=alias,
            lookup_type="alias",
        ) from exc

    if rebuild:
        index_manager = IndexManager(
            index, index.Index.name, es_client
        )  # This should not be recreated every time.

        logger.info("Destroying index", index=alias)
        await index_manager.delete_current_index_unsafe()
        logger.info("Recreating index", index=alias)
        await index_manager.initialize_index()

    await queue_task_with_trace(repair_task)
    return JSONResponse(
        content={
            "status": "ok",
            "message": f"Repair task for index {alias} has been initiated.",
        },
        status_code=status.HTTP_202_ACCEPTED,
    )
