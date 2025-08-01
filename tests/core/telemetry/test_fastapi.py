"""Test script to demonstrate the TracingMiddleware functionality."""

from typing import Annotated

from fastapi import FastAPI, Path
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.telemetry.fastapi import FastAPITracingMiddleware


def setup_tracing():
    """Set up OpenTelemetry for testing."""
    # Set up tracer
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)

    # Set up in-memory exporter to capture spans for testing
    memory_exporter = InMemorySpanExporter()
    span_processor = SimpleSpanProcessor(memory_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)

    return tracer, memory_exporter


def test_tracing_middleware():
    """Test the TracingMiddleware with a simple FastAPI app."""
    tracer, memory_exporter = setup_tracing()

    app = FastAPI()
    app.add_middleware(FastAPITracingMiddleware)

    @app.get("/test/{item_id}/")
    async def test_endpoint(
        item_id: Annotated[str, Path(...)], query_param: str = "default"
    ) -> dict[str, str]:
        return {"item_id": item_id, "query_param": query_param}

    client = TestClient(app)

    with tracer.start_as_current_span("test_request"):
        client.get("/test/123?query_param=test_value&another_param=another_value")

    # Get the spans from the in-memory exporter
    spans = memory_exporter.get_finished_spans()

    # Find our test span
    test_span = None
    for span in spans:
        if span.name == "test_request":
            test_span = span
            break

    assert test_span is not None, "Test span not found"

    # Verify the attributes were set by the middleware
    attributes = test_span.attributes
    assert attributes["http.request.query.query_param"] == "test_value"
    assert attributes["http.request.query.another_param"] == "another_value"
    assert attributes["http.request.path.item_id"] == "123"
