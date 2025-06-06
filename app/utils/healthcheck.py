"""Router for healthcheck endpoints."""

from typing import Annotated

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.persistence.es.client import get_client
from app.persistence.sql.session import get_session
from app.tasks import broker

router = APIRouter(prefix="/healthcheck", tags=["healthcheck"])
logger = get_logger()
settings = get_settings()


class HealthCheckOptions(BaseModel):
    """Optional flags to toggle what to health check."""

    worker: bool = True
    database: bool = True
    elasticsearch: bool = True
    azure_blob_storage: bool = True


@router.get("/", status_code=status.HTTP_200_OK)
async def get_healthcheck(
    healthcheck_options: Annotated[HealthCheckOptions, Depends()],
    db_session: Annotated[AsyncSession, Depends(get_session)],
    es_client: Annotated[AsyncElasticsearch, Depends(get_client)],
) -> JSONResponse:
    """Verify we are able to connect to the database."""
    if healthcheck_options.worker:
        # If we want to do this properly (testing the worker), we need to set up a
        # taskiq result backend: https://taskiq-python.github.io/extending-taskiq/result-backend.html
        # and then call healthcheck() with it.
        # For now we just check we can write to the queue.
        await _stub.kiq()

    result = await healthcheck(db_session, es_client, healthcheck_options)
    if result:
        raise HTTPException(status_code=500, detail=result)
    return JSONResponse(content={"status": "ok"})


@broker.task
async def _stub() -> None:
    """Fake task."""
    return


async def healthcheck(
    db_session: AsyncSession,
    es_client: AsyncElasticsearch,
    healthcheck_options: HealthCheckOptions,
) -> str | None:
    """Run healthcheck. Returns an error message if failed else None."""
    logger.info("Running healthcheck", extra={"options": healthcheck_options})

    if healthcheck_options.database:
        try:
            await db_session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Database connection failed.")
            return "Database connection failed."

    if healthcheck_options.elasticsearch:
        try:
            await es_client.info()
        except Exception:
            logger.exception("Elasticsearch connection failed.")
            return "Elasticsearch connection failed."

    if healthcheck_options.azure_blob_storage:
        if not settings.azure_blob_config:
            return "No Azure blob config provided."

        try:
            async with BlobServiceClient(
                account_url=settings.azure_blob_config.account_url,
                credential=DefaultAzureCredential()
                if settings.azure_blob_config.uses_managed_identity
                else settings.azure_blob_config.credential,
            ) as client:
                container = client.get_container_client(
                    settings.azure_blob_config.container
                )
                await container.get_container_properties()

        except Exception:
            logger.exception("Blob storage connection failed.")
            return "Blob storage connection failed."

    return None
