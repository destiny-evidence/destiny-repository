"""Router for healthcheck endpoints."""

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger()
settings = get_settings()


class HealthCheckOptions(BaseModel):
    """Optional flags to toggle what to health check."""

    worker: bool = True
    database: bool = True
    elasticsearch: bool = True
    azure_blob_storage: bool = True


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
            await es_client.cluster.health()
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
