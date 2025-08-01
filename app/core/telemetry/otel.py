"""Configure OpenTelemetry for tracing and metrics collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.logger import get_logger
from app.core.telemetry.attributes import Attributes

if TYPE_CHECKING:
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

    headers = {}
    if config.api_key:
        headers["x-honeycomb-team"] = config.api_key

    resource = Resource.create(
        {
            Attributes.SERVICE_NAMESPACE: "destiny",
            Attributes.SERVICE_NAME: f"{app_name}-{env.value}",
            Attributes.SERVICE_VERSION: app_version,
            Attributes.DEPLOYMENT_ENVIRONMENT: env.value,
        }
    )

    tracer_provider = TracerProvider(resource=resource)

    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=str(config.trace_endpoint),
                # Dataset is inferred from resource.service_name
                headers=headers,
            ),
        )
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=str(config.meter_endpoint),
                    headers=headers
                    | {"x-honeycomb-dataset": f"metrics-{app_name}-{env.value}"},
                )
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)
