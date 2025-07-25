"""Configure OpenTelemetry for tracing and metrics collection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry import context, metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv._incubating.attributes import (
    deployment_attributes as _deployment_attributes,
)
from opentelemetry.semconv._incubating.attributes import (
    service_attributes as _service_attributes,
)
from opentelemetry.semconv.attributes import service_attributes
from opentelemetry.trace import Span, SpanKind
from taskiq import (
    AsyncTaskiqDecoratedTask,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)

from app.core.logger import get_logger

if TYPE_CHECKING:
    from opentelemetry.context import Context

    from app.core.config import Environment, OTelConfig

logger = get_logger()
tracer = trace.get_tracer(__name__)


def configure_otel(
    config: OTelConfig, app_name: str, app_version: str, env: Environment
) -> None:
    """
    Configure OpenTelemetry for tracing and metrics.

    This function sets up the OpenTelemetry SDK with OTLP exporters for both
    traces and metrics globally, allowing for collection and export of telemetry data
    with no need to pass around objects.
    """
    # Ensures this can only be called once (basically helps on dev autoreload)
    if trace._TRACER_PROVIDER_SET_ONCE._done:  # noqa: SLF001
        return

    resource = Resource.create(
        {
            _service_attributes.SERVICE_NAMESPACE: "destiny",
            service_attributes.SERVICE_NAME: app_name,
            service_attributes.SERVICE_VERSION: app_version,
            _deployment_attributes.DEPLOYMENT_ENVIRONMENT: env.value,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    # Configure trace exporter
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=str(config.trace_endpoint)))
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=str(config.meter_endpoint))
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)


class TaskiqTracingMiddleware(TaskiqMiddleware):
    """
    Custom TaskIQ middleware for OpenTelemetry tracing.

    This middleware automatically extracts trace context from incoming messages
    and creates spans for task execution, providing seamless distributed tracing
    across the task queue.
    """

    def __init__(self) -> None:
        """Initialize the middleware."""
        super().__init__()
        self._current_span: Span | None = None
        self._token: context.Token[Context] | None = None

    @staticmethod
    async def kiq(
        task: AsyncTaskiqDecoratedTask,
        *args: object,
        **kwargs: object,
    ) -> None:
        """
        Wrap around taskiq queueing to inject OpenTelemetry trace context.

        All tasks should be queued through this function to ensure
        that the OpenTelemetry trace context is automatically injected.
        """
        with tracer.start_as_current_span(
            f"queue.{task.task_name}",
            kind=SpanKind.PRODUCER,
            attributes={
                "task.name": task.task_name,
                "messaging.operation": "send",
                "messaging.system": "taskiq",
            },
        ):
            # Inject the current trace context into the message carrier
            # for distributed tracing
            carrier: dict[str, Any] = {}
            propagate.inject(carrier)

            # Queue the task with the trace context
            await task.kiq(
                *args,
                **kwargs,
                trace_context=carrier,
            )

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """
        Extract trace context and start a span before task execution.

        Args:
            message: The incoming TaskIQ message

        Returns:
            The message with trace context removed.

        """
        # Extract trace context from message kwargs
        carrier: dict[str, Any] = {}
        if (
            hasattr(message, "kwargs")
            and message.kwargs
            and "trace_context" in message.kwargs
        ):
            carrier = message.kwargs.pop("trace_context", {})

        logger.debug(
            "Received task with trace context",
            extra={
                "task_name": message.task_name,
                "carrier_keys": list(carrier.keys()),
            },
        )

        # Let OpenTelemetry extract the context
        ctx = propagate.extract(carrier)

        # Start a new span for the task execution using the extracted context
        self._current_span = tracer.start_span(
            f"execute.{message.task_name}",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                "task.name": message.task_name,
                "task.id": message.task_id,
                "messaging.operation": "receive",
                "messaging.system": "taskiq",
            },
        )
        # Activate the context for this span during task execution
        self._token = context.attach(trace.set_span_in_context(self._current_span))

        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult[Any]
    ) -> None:
        """
        Complete the span after task execution.

        Args:
            message: The TaskIQ message that was executed
            result: The result of the task execution

        """
        if self._current_span:
            try:
                if result.is_err:
                    # Task failed - record the error
                    self._current_span.set_status(
                        trace.Status(trace.StatusCode.ERROR, str(result.error))
                    )
                    if result.error:
                        self._current_span.record_exception(result.error)
                else:
                    # Task succeeded
                    self._current_span.set_status(trace.Status(trace.StatusCode.OK))

                # End the span
                self._current_span.__exit__(None, None, None)

                logger.debug(
                    "Completed OpenTelemetry span for task",
                    extra={
                        "task_name": message.task_name,
                        "task_id": message.task_id,
                        "success": not result.is_err,
                    },
                )

            finally:
                self._current_span = None

                # Detach the context
                if self._token:
                    context.detach(self._token)
                    self._token = None
