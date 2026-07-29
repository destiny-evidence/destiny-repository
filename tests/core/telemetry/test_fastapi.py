"""Test script to demonstrate the TracingMiddleware functionality."""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.telemetry.fastapi import FastAPITracingMiddleware, trace_path_params


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


def _find_span(memory_exporter: InMemorySpanExporter, name: str) -> ReadableSpan | None:
    for span in memory_exporter.get_finished_spans():
        if span.name == name:
            return span
    return None


def test_middleware_traces_query_params():
    """Test that query params can be traced using the middleware."""
    tracer, memory_exporter = setup_tracing()

    app = FastAPI()
    app.add_middleware(FastAPITracingMiddleware)

    router = APIRouter()

    @router.get("/test/{item_id}")
    async def test_endpoint(
        item_id: Annotated[str, Path(...)], query_param: str = "default"
    ) -> dict[str, str]:
        return {"item_id": item_id, "query_param": query_param}

    app.include_router(router)
    client = TestClient(app)

    with tracer.start_as_current_span("test_request"):
        client.get("/test/123?query_param=test_value&another_param=another_value")

    test_span = _find_span(memory_exporter, "test_request")
    assert test_span is not None, "Test span not found"

    attributes = test_span.attributes
    assert attributes["http.request.query.query_param"] == "test_value"
    assert attributes["http.request.query.another_param"] == "another_value"


def test_path_params_traced_via_dependency():
    """# Test that path params can be traced using the dependency on the router."""
    tracer, memory_exporter = setup_tracing()

    app = FastAPI()
    app.add_middleware(FastAPITracingMiddleware)

    router = APIRouter(dependencies=[Depends(trace_path_params)])

    @router.get("/test/{item_id}")
    async def test_endpoint(item_id: Annotated[str, Path(...)]) -> dict[str, str]:
        return {"item_id": item_id}

    app.include_router(router)
    client = TestClient(app)

    with tracer.start_as_current_span("test_request"):
        client.get("/test/123")

    test_span = _find_span(memory_exporter, "test_request")
    assert test_span is not None, "Test span not found"

    attributes = test_span.attributes
    assert attributes["http.request.path.item_id"] == "123"
