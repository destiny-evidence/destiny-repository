"""Tests for the logger module."""

from unittest.mock import patch

import pytest
import structlog

from app.core.config import LogLevel
from app.core.telemetry.logger import LogLevelSampler, OTelAttributeFilter


class TestLogLevelSampler:
    """Tests for LogLevelSampler."""

    def test_rate_1_always_passes(self):
        """A rate of 1.0 should always pass through logs."""
        sampler = LogLevelSampler({LogLevel.DEBUG: 1.0})
        event_dict = {"level": "debug", "event": "test message"}

        result = sampler(None, "debug", event_dict)

        assert result == event_dict

    def test_rate_0_always_drops(self):
        """A rate of 0.0 should always drop logs."""
        sampler = LogLevelSampler({LogLevel.DEBUG: 0.0})
        event_dict = {"level": "debug", "event": "test message"}

        with pytest.raises(structlog.DropEvent):
            sampler(None, "debug", event_dict)

    def test_partial_rate_samples_randomly(self):
        """A partial rate should sample based on random value."""
        sampler = LogLevelSampler({LogLevel.INFO: 0.5})
        event_dict = {"level": "info", "event": "test message"}

        with patch("app.core.telemetry.logger.random.random", return_value=0.3):
            result = sampler(None, "info", event_dict)
            assert result == event_dict

        with (
            patch("app.core.telemetry.logger.random.random", return_value=0.7),
            pytest.raises(structlog.DropEvent),
        ):
            sampler(None, "info", event_dict)

    def test_unspecified_level_defaults_to_1(self):
        """Unspecified log levels should default to rate 1.0 (pass through)."""
        sampler = LogLevelSampler({LogLevel.DEBUG: 0.0})
        event_dict = {"level": "info", "event": "test message"}

        result = sampler(None, "info", event_dict)

        assert result == event_dict

    def test_missing_level_defaults_to_pass(self):
        """Events without a level key should pass through."""
        sampler = LogLevelSampler({LogLevel.DEBUG: 0.0})
        event_dict = {"event": "test message"}

        result = sampler(None, "debug", event_dict)

        assert result == event_dict


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
