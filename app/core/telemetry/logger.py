"""Functionality for logging with structured attributes."""

import logging

from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.util.types import AnyValue


# https://github.com/open-telemetry/opentelemetry-python/issues/3649#issuecomment-2295549483
class AttrFilteredLoggingHandler(LoggingHandler):
    """Logging handler that filters out specific attributes from log records."""

    _drop_attributes = ("_logger", "websocket")

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> dict[str, AnyValue]:
        """Get attributes from the log record, filtering out specific ones."""
        attributes = dict(LoggingHandler._get_attributes(record))  # noqa: SLF001
        for attr in AttrFilteredLoggingHandler._drop_attributes:
            if attr in attributes:
                del attributes[attr]
        return attributes
