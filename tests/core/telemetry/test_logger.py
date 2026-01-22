"""Tests for the logger module."""

import logging
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from app.core.config import LogSamplingConfig
from app.core.telemetry.logger import OrphanLogLevelSamplingFilter, OTelAttributeFilter


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


class TestOTelAttributeFilter:
    """Tests for OTelAttributeFilter."""

    def test_filters_specified_keys(self):
        """Should remove specified keys from event dict."""
        filter_proc = OTelAttributeFilter("timestamp", "extra")
        event_dict = {"event": "test", "timestamp": "2024-01-01", "extra": "value"}

        result = filter_proc(None, "info", event_dict)

        assert "timestamp" not in result
        assert "extra" not in result
        assert result["event"] == "test"

    def test_handles_missing_keys(self):
        """Should not raise if keys to drop are missing."""
        filter_proc = OTelAttributeFilter("timestamp", "nonexistent")
        event_dict = {"event": "test"}

        result = filter_proc(None, "info", event_dict)

        assert result == {"event": "test"}

    def test_no_keys_passes_through(self):
        """With no keys specified, should pass through unchanged."""
        filter_proc = OTelAttributeFilter()
        event_dict = {"event": "test", "timestamp": "2024-01-01"}

        result = filter_proc(None, "info", event_dict)

        assert result == event_dict
