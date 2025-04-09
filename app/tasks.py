"""Tasks module for the DESTINY Climate and Health Repository API."""

from taskiq import TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker

from app.core.config import get_settings
from app.persistence.sql.session import db_manager

settings = get_settings()

broker = AioPikaBroker(settings.message_broker_url)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state: TaskiqState) -> None:
    """Initialize the database when the worker is ready."""
    db_manager.init(str(settings.db_url))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(_state: TaskiqState) -> None:
    """Close DB connections when the worker is shutting down."""
    await db_manager.close()
