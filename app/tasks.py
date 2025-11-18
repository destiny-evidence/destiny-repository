"""Tasks module for the DESTINY Climate and Health Repository API."""

from taskiq import AsyncBroker, InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_aio_pika import AioPikaBroker

from app.core.azure_service_bus_broker import AzureServiceBusBroker
from app.core.config import Environment, get_settings
from app.core.telemetry.logger import logger_configurer
from app.core.telemetry.otel import configure_otel
from app.core.telemetry.taskiq import TaskiqTracingMiddleware
from app.persistence.es.client import es_manager
from app.persistence.sql.session import db_manager

settings = get_settings()

logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

broker: AsyncBroker = AzureServiceBusBroker(
    namespace=settings.message_broker_namespace,
    queue_name=settings.message_broker_queue_name,
    max_lock_renewal_duration=settings.message_lock_renewal_duration,
)

if settings.env == Environment.LOCAL or settings.tests_use_rabbitmq:
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

    AioPikaInstrumentor().instrument()
    broker = AioPikaBroker(settings.message_broker_url)

elif settings.env == "test":
    broker = InMemoryBroker()


# Add OpenTelemetry middleware to all brokers
if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config, settings.app_name, settings.app_version, settings.env
    )
    broker.add_middlewares(TaskiqTracingMiddleware())


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state: TaskiqState) -> None:
    """Initialize the database when the worker is ready."""
    db_manager.init(settings.db_config, settings.app_name)
    await es_manager.init(settings.es_config)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(_state: TaskiqState) -> None:
    """Close DB connections when the worker is shutting down."""
    await db_manager.close()
    await es_manager.close()


# Scheduler for development - only active in local environment
scheduler = None
if settings.env == Environment.LOCAL:
    from taskiq import TaskiqScheduler

    scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
