"""Configure OpenTelemetry for tracing and metrics collection."""

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.attributes import service_attributes

from app.core.config import OTelConfig


def configure_otel(config: OTelConfig, app_name: str, app_version: str) -> None:
    """
    Configure OpenTelemetry for tracing and metrics.

    This function sets up the OpenTelemetry SDK with OTLP exporters for both
    traces and metrics globally, allowing for collection and export of telemetry data
    with no need to pass around objects.
    """
    resource = Resource.create(
        {
            service_attributes.SERVICE_NAME: app_name,
            service_attributes.SERVICE_VERSION: app_version,
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
