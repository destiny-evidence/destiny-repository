"""Tasks module for the DESTINY Climate and Health Repository API."""

import asyncio

from celery import Celery
from celery.signals import worker_init, worker_shutdown

from app.core.config import get_settings
from app.persistence.sql.session import db_manager

settings = get_settings()

celery_app = Celery("tasks", broker=settings.celery_broker_url)


@worker_init.connect
def on_worker_init(sender: None, **kwargs: dict) -> None:  # noqa: ARG001
    """Initialize the database when the worker is ready."""
    db_manager.init(str(settings.db_url))


@worker_shutdown.connect
def on_worker_shutdown(sender: None, **kwargs: dict) -> None:  # noqa: ARG001
    """Close DB connections when the worker is shutting down."""
    asyncio.ensure_future(db_manager.close())  # noqa: RUF006


celery_app.autodiscover_tasks(["app.domain.imports"])
