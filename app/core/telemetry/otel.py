"""Configure OpenTelemetry for tracing and metrics collection."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Link, Span, SpanContext
from opentelemetry.util.types import AttributeValue

from app.core.telemetry.attributes import Attributes
from app.core.telemetry.logger import (
    AttrFilteredLoggingHandler,
    ElasticTransportFilter,
    get_logger,
    logger_configurer,
)
from app.core.telemetry.processors import FilteringBatchSpanProcessor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from app.core.config import Environment, OTelConfig

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


def get_current_trace_link() -> dict[str, str]:
    """Capture the current span context as a trace link dict."""
    span_context = trace.get_current_span().get_span_context()
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def configure_otel(
    config: OTelConfig,
    app_name: str,
    app_version: str,
    env: Environment,
    trace_config: str | None = None,
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

    headers = {}
    if config.api_key:
        headers["x-honeycomb-team"] = config.api_key

    service_instance_id = str(uuid.uuid4())

    ## Traces
    resource = Resource.create(
        {
            Attributes.SERVICE_NAMESPACE: "destiny",
            Attributes.SERVICE_NAME: f"{app_name}-{env.value}",
            Attributes.SERVICE_VERSION: app_version,
            Attributes.SERVICE_INSTANCE_ID: service_instance_id,
            Attributes.DEPLOYMENT_ENVIRONMENT: env.value,
            Attributes.SERVICE_CONFIG: trace_config or "",
        }
    )

    tracer_provider = TracerProvider(resource=resource)

    span_processor = FilteringBatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=str(config.trace_endpoint),
            # Dataset is inferred from resource.service_name
            headers=headers,
            timeout=config.timeout,
        ),
    )
    if not config.instrument_sql:
        # Filter out auto-instrumented SQLAlchemy spans
        span_processor.add_condition(
            lambda span: (
                span.instrumentation_scope.name
                == "opentelemetry.instrumentation.sqlalchemy"
                if span.instrumentation_scope
                else False
            )
        )
    if not config.instrument_elasticsearch:
        # Filter out auto-instrumented Elasticsearch spans and logs
        span_processor.add_condition(
            lambda span: (
                span.instrumentation_scope.name == "elasticsearch-api"
                if span.instrumentation_scope
                else False
            )
        )
    if not config.instrument_taskiq:
        # Filter out auto-instrumented TaskIQ spans
        span_processor.add_condition(
            lambda span: (
                span.instrumentation_scope.name
                == "opentelemetry.instrumentation.aio_pika"
                if span.instrumentation_scope
                else False
            )
        )

    tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(tracer_provider)

    ## Metrics
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=str(config.meter_endpoint),
                    headers=headers | {"x-honeycomb-dataset": "metrics-repository"},
                    timeout=config.timeout,
                )
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)

    ## Logs
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)
    exporter = OTLPLogExporter(
        endpoint=str(config.log_endpoint),
        headers=headers,
        timeout=config.timeout,
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    handler = AttrFilteredLoggingHandler(logger_provider=logger_provider)
    if not config.instrument_elasticsearch:
        # Explicitly remove elastic transport logs - these come from spans that we
        # filter out above, so we don't need the logs either in Honeycomb. They aren't
        # filtered out by our normal orphaned log sampling as their trace_id and span_id
        # exist, just are head-sampled-out.
        handler.addFilter(ElasticTransportFilter())
    logger_configurer.configure_otel_logger(
        handler, orphan_log_sampling_config=config.orphan_log_sample_config
    )

    logger.info("Opentelemetry configured", service_instance_id=service_instance_id)


@contextlib.contextmanager
def new_linked_trace(
    name: str,
    attributes: Mapping[Attributes, AttributeValue] | None = None,
    *,
    create_parent: bool = False,
) -> Iterator[Span]:
    """
    Create a decoupled trace boundary with a parent span and linked child trace.

    :param name: The name of the span.
    :type name: str
    :param attributes: Attributes to set on created spans.
    :type attributes: dict[Attributes, AttributeValue] | None
    :param create_parent: Whether to create a parent span. This allows you to see
        the invokation of the decoupled trace in the parent trace - but beware of
        O(n) span explosion if used in loops!
    :type create_parent: bool
    :rtype: Iterator[Span]

    Example:
        with tracer.start_as_current_span("Big Operation"):
            with new_linked_trace("Small decoupled operation"):
                do_work()

    """
    # Attributes is StrEnum so has str but we need to cast for mypy
    _attributes = cast(Mapping[str, AttributeValue], attributes) if attributes else {}

    def _create_child(link_context: SpanContext) -> Iterator[Span]:
        link = Link(
            SpanContext(
                trace_id=link_context.trace_id,
                span_id=link_context.span_id,
                is_remote=False,
            )
        )
        with tracer.start_as_current_span(
            name, attributes=_attributes, context=Context(), links=[link]
        ) as child_span:
            yield child_span

    if create_parent:
        # Create parent span, then independent child linked to parent
        with tracer.start_as_current_span(name, attributes=_attributes) as parent_span:
            yield from _create_child(parent_span.get_span_context())
    else:
        # Just create independent child linked to current context
        yield from _create_child(trace.get_current_span().get_span_context())
