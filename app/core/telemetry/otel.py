"""Configure OpenTelemetry for tracing and metrics collection."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from app.core.telemetry.attributes import Attributes
from app.core.telemetry.logger import (
    AttrFilteredLoggingHandler,
    get_logger,
    logger_configurer,
)
from app.core.telemetry.processors import FilteringBatchSpanProcessor

if TYPE_CHECKING:
    from app.core.config import Environment, OTelConfig

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


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
        # Filter out auto-instrumented Elasticsearch spans
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
    logger_configurer.configure_otel_logger(handler)

    logger.info("Opentelemetry configured", service_instance_id=service_instance_id)
