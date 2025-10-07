"""Router for system utility endpoints."""

from typing import Annotated

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
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
from app.core.exceptions import ESNotFoundError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.es import (
    ReferenceDocument,
    RobotAutomationPercolationDocument,
)
from app.domain.references.tasks import (
    repair_reference_index,
    repair_robot_automation_percolation_index,
)
from app.persistence.es.client import get_client
from app.persistence.es.index_manager import IndexManager
from app.persistence.sql.session import get_session
from app.system.healthcheck import HealthCheckOptions, healthcheck

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/system", tags=["system utilities"])


def index_managers(
    es_client: Annotated[AsyncElasticsearch, Depends(get_client)],
) -> dict[str, IndexManager]:
    """Create index managers for each index."""
    return {
        ReferenceDocument.Index.name: IndexManager(
            document_class=ReferenceDocument,
            alias_name=ReferenceDocument.Index.name,
            repair_task=repair_reference_index,
            client=es_client,
        ),
        RobotAutomationPercolationDocument.Index.name: IndexManager(
            document_class=RobotAutomationPercolationDocument,
            alias_name=RobotAutomationPercolationDocument.Index.name,
            repair_task=repair_robot_automation_percolation_index,
            client=es_client,
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
    index_managers: Annotated[dict[str, IndexManager], Depends(index_managers)],
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
        index_manager = index_managers[alias]
    except KeyError as exc:
        raise ESNotFoundError(
            detail=f"Index {alias} not found.",
            lookup_model="meta:index",
            lookup_value=alias,
            lookup_type="alias",
        ) from exc

    if rebuild:
        await index_manager.delete_and_recreate_index()

    await index_manager.repair_index()
    return JSONResponse(
        content={
            "status": "ok",
            "message": f"Repair task for index {alias} has been initiated.",
        },
        status_code=status.HTTP_202_ACCEPTED,
    )
