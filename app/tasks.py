"""Tasks module for the DESTINY Climate and Health Repository API."""

from taskiq import AsyncBroker, InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker

from app.core.azure_service_bus_broker import AzureServiceBusBroker
from app.core.config import get_settings
from app.persistence.sql.session import db_manager

settings = get_settings()

broker: AsyncBroker = AzureServiceBusBroker(
    namespace=settings.message_broker_namespace,
    queue_name=settings.message_broker_queue_name,
)

if settings.env == "dev":
    broker = AioPikaBroker(settings.message_broker_url)
elif settings.env == "test":
    broker = InMemoryBroker()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state: TaskiqState) -> None:
    """Initialize the database when the worker is ready."""
    db_manager.init(str(settings.db_url))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(_state: TaskiqState) -> None:
    """Close DB connections when the worker is shutting down."""
    await db_manager.close()
