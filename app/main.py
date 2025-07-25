"""Main module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.root import register_api
from app.core.config import get_settings
from app.core.logger import configure_logger, get_logger
from app.core.telemetry import configure_otel
from app.persistence.es.client import es_manager
from app.persistence.sql.session import db_manager
from app.tasks import broker

settings = get_settings()
if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config, settings.app_name, settings.app_version, settings.env
    )

logger = get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifespan hook for FastAPI."""
    # TODO(Adam): implement similar pattern for blob storage  # noqa: TD003
    db_manager.init(settings.db_config, settings.app_name)
    await es_manager.init(settings.es_config)
    await broker.startup()

    yield

    await broker.shutdown()
    await db_manager.close()
    await es_manager.close()


app = register_api(lifespan)

configure_logger(rich_rendering=settings.running_locally)
