"""Tests for the logger module."""

import io
import logging
import logging.config
from collections.abc import Generator
from unittest.mock import patch

import pytest
import structlog
from fastapi_cli.utils.cli import get_uvicorn_log_config
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from uvicorn.config import LOGGING_CONFIG

from app.core.config import LogLevel, LogSamplingConfig
from app.core.telemetry.logger import (
    LoggerConfigurer,
    OrphanLogLevelSamplingFilter,
    UvicornAccessFilter,
    add_trace_context,
    filter_otel_attributes,
    logger_configurer,
)


class TestOrphanLogLevelSamplingFilter:
    """Tests for OrphanLogLevelSamplingFilter."""

    def _make_record(self, level: int) -> logging.LogRecord:
        """Create a LogRecord with the given level."""
        return logging.LogRecord(
            name="test",
            level=level,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

    def test_rate_1_always_passes(self):
        """A rate of 1.0 should always pass through logs."""
        config = LogSamplingConfig(debug_sample_rate=1.0)
        filter_ = OrphanLogLevelSamplingFilter(config)
        record = self._make_record(logging.DEBUG)

        assert filter_.filter(record) is True

    def test_rate_0_always_drops(self):
        """A rate of 0.0 should always drop logs."""
        config = LogSamplingConfig(debug_sample_rate=0.0)
        filter_ = OrphanLogLevelSamplingFilter(config)
        record = self._make_record(logging.DEBUG)

        assert filter_.filter(record) is False

    def test_partial_rate_samples_randomly(self):
        """A partial rate should sample based on random value."""
        config = LogSamplingConfig(info_sample_rate=0.5)
        filter_ = OrphanLogLevelSamplingFilter(config)
        record = self._make_record(logging.INFO)

        with patch("app.core.telemetry.logger.random.random", return_value=0.3):
            assert filter_.filter(record) is True

        with patch("app.core.telemetry.logger.random.random", return_value=0.7):
            assert filter_.filter(record) is False

    def test_unspecified_level_uses_default(self):
        """Unspecified log levels should use default rates."""
        config = LogSamplingConfig(debug_sample_rate=0.0)
        filter_ = OrphanLogLevelSamplingFilter(config)
        # INFO defaults to 1.0
        record = self._make_record(logging.INFO)

        assert filter_.filter(record) is True

    def test_logs_within_span_always_pass(self):
        """Logs within an active span should always pass regardless of sample rate."""
        config = LogSamplingConfig(debug_sample_rate=0.0)
        filter_ = OrphanLogLevelSamplingFilter(config)
        record = self._make_record(logging.DEBUG)

        # Create a real tracer and span
        tracer_provider = TracerProvider()
        tracer = tracer_provider.get_tracer(__name__)

        with tracer.start_as_current_span("test-span"):
            # Verify we're in a valid span context
            assert trace.get_current_span().get_span_context().is_valid
            # Log should pass even with 0.0 sample rate
            assert filter_.filter(record) is True


@pytest.fixture
def _restore_uvicorn_loggers() -> Generator[None]:
    """Snapshot and restore uvicorn logger state around a dictConfig call."""
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).filters[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
        )
        for name in names
    }
    root_handlers, root_level = logging.root.handlers[:], logging.root.level
    yield
    logging.root.handlers[:] = root_handlers
    logging.root.setLevel(root_level)
    for name, (handlers, filters, level, propagate, disabled) in saved.items():
        restored = logging.getLogger(name)
        restored.handlers[:] = handlers
        restored.filters[:] = filters
        restored.setLevel(level)
        restored.propagate = propagate
        restored.disabled = disabled


@pytest.fixture
def _restore_logging_config() -> Generator[None]:
    """Snapshot and restore root handlers and structlog config around a reconfigure."""
    saved_structlog = structlog.get_config()
    root_handlers, root_level = logging.root.handlers[:], logging.root.level
    yield
    logging.root.handlers[:] = root_handlers
    logging.root.setLevel(root_level)
    structlog.configure(**saved_structlog)


class TestConsoleElasticTransport:
    """Tests for elastic transport noise on the console handler."""

    @pytest.mark.usefixtures("_restore_logging_config")
    def test_elastic_transport_is_dropped_but_app_logs_are_not(self):
        """
        Logs every Elasticsearch request, and stdout is the billed destination.

        OTEL keeps its own copy where instrument_elasticsearch is on.
        """
        structlog.reset_defaults()
        LoggerConfigurer().configure_console_logger(
            log_level=LogLevel.INFO, rich_rendering=False
        )
        stream = io.StringIO()
        for handler in logging.root.handlers:
            handler.setStream(stream)

        logging.getLogger("elastic_transport.transport").info(
            "GET /reference_v3/_search"
        )
        logging.getLogger("app.domain.references.tasks").info("kept this one")

        written = stream.getvalue()
        assert "kept this one" in written
        assert "_search" not in written


class TestUvicornAccessFilter:
    """Tests for UvicornAccessFilter."""

    def test_drops_every_record(self):
        """The filter drops access records regardless of level or content."""
        filter_ = UvicornAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )

        assert filter_.filter(record) is False

    @pytest.mark.usefixtures("_restore_uvicorn_loggers")
    def test_access_log_stays_silent_after_uvicorn_log_config(self):
        """Uvicorn's dictConfig resets `disabled`, so the filter must do the work."""
        logging.config.dictConfig(LOGGING_CONFIG)
        access = logging.getLogger("uvicorn.access")
        stream = io.StringIO()
        for handler in access.handlers:
            handler.setStream(stream)

        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "10.0.0.1:1234",
            "GET",
            "/v1/system/ping/",
            "1.1",
            200,
        )

        assert access.disabled is False
        assert stream.getvalue() == ""

    @pytest.mark.usefixtures("_restore_uvicorn_loggers")
    def test_uvicorn_error_log_is_not_silenced(self):
        """Startup lines and ASGI tracebacks ride uvicorn.error and must survive."""
        logging.config.dictConfig(LOGGING_CONFIG)
        stream = io.StringIO()
        # uvicorn.error carries no handler of its own; the parent serves it.
        for handler in logging.getLogger("uvicorn").handlers:
            handler.setStream(stream)

        logging.getLogger("uvicorn.error").info("Application startup complete.")

        assert "Application startup complete." in stream.getvalue()

    @pytest.mark.usefixtures("_restore_uvicorn_loggers")
    def test_uvicorn_logs_reach_root_exactly_once(self):
        """Uvicorn's own stderr handler duplicates what our root handler renders."""
        logging.config.dictConfig(LOGGING_CONFIG)
        own_stream = io.StringIO()
        for handler in logging.getLogger("uvicorn").handlers:
            handler.setStream(own_stream)
        root_stream = io.StringIO()
        logging.root.addHandler(logging.StreamHandler(root_stream))
        logging.root.setLevel(logging.INFO)

        logger_configurer.route_uvicorn_logs_to_root()
        logging.getLogger("uvicorn.error").info("Application startup complete.")

        assert own_stream.getvalue() == ""
        assert "Application startup complete." in root_stream.getvalue()

    @pytest.mark.usefixtures("_restore_uvicorn_loggers")
    def test_lines_logged_before_the_lifespan_still_duplicate(self):
        """
        Uvicorn logs two lines before entering the lifespan that reroutes it.

        `fastapi run` leaves `uvicorn.propagate` at its default, so until the
        lifespan runs each record reaches both uvicorn's handler and ours.
        """
        logging.config.dictConfig(get_uvicorn_log_config())
        own_stream = io.StringIO()
        for handler in logging.getLogger("uvicorn").handlers:
            handler.setStream(own_stream)
        root_stream = io.StringIO()
        logging.root.addHandler(logging.StreamHandler(root_stream))
        logging.root.setLevel(logging.INFO)

        logging.getLogger("uvicorn.error").info("Started server process [1]")

        assert logging.getLogger("uvicorn").propagate is True
        assert "Started server process" in own_stream.getvalue()
        assert "Started server process" in root_stream.getvalue()


class TestTraceContext:
    """Tests for trace correlation on log events."""

    def test_adds_ids_inside_a_span(self):
        """Console logs are plain text, so the ids must ride in the event itself."""
        tracer = TracerProvider().get_tracer(__name__)

        with tracer.start_as_current_span("test-span") as span:
            event_dict = add_trace_context(None, "info", {})
            span_context = span.get_span_context()

        assert event_dict["trace_id"] == format(span_context.trace_id, "032x")
        assert event_dict["span_id"] == format(span_context.span_id, "016x")

    def test_adds_nothing_outside_a_span(self):
        """A log with no active span has nothing to correlate to."""
        assert add_trace_context(None, "info", {}) == {}

    def test_otel_body_does_not_repeat_trace_context(self):
        """OTLP transports trace context on the record, so the body would duplicate."""
        event_dict = {
            "event": "something",
            "timestamp": "2026-09-22T00:00:00Z",
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
            "span_id": "b7ad6b7169203331",
        }

        assert filter_otel_attributes(None, "info", event_dict) == {
            "event": "something"
        }

    @pytest.mark.usefixtures("_restore_logging_config")
    def test_console_output_carries_the_trace_id(self):
        """The whole point is correlating a stdout line back to its trace."""
        structlog.reset_defaults()
        LoggerConfigurer().configure_console_logger(
            log_level=LogLevel.INFO, rich_rendering=False
        )
        stream = io.StringIO()
        for handler in logging.root.handlers:
            handler.setStream(stream)
        tracer = TracerProvider().get_tracer(__name__)

        with tracer.start_as_current_span("test-span") as span:
            structlog.get_logger("app.test").info("inside a span")
            expected = format(span.get_span_context().trace_id, "032x")

        assert expected in stream.getvalue()
