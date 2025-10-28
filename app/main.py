"""Main module for the DESTINY Climate and Health Repository API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.root import register_api
from app.core.config import get_settings
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.persistence.es.client import es_manager
from app.persistence.sql.session import db_manager
from app.tasks import broker

logger = get_logger(__name__)
settings = get_settings()
logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config, settings.app_name, settings.app_version, settings.env
    )


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


app = register_api(
    lifespan,
    [str(origin) for origin in settings.cors_allow_origins],
    otel_enabled=settings.otel_enabled,
)
