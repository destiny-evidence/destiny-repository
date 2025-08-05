"""Functionality for logging with structured attributes."""

import logging
import sys
from typing import cast

import structlog
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.util.types import AnyValue

from app.core.config import LogLevel


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


def filter_otel_attributes(
    _logger: object, _method_name: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    """Filter out attributes that are unnecessary for OpenTelemetry."""
    # Remove timestamp from the event so we can aggregate event bodies
    # otel will add its own timestamp to the event
    event_dict.pop("timestamp", None)
    return event_dict


class LoggerConfigurer:
    """Class to configure application logging."""

    def __init__(self) -> None:
        """Initialize the logger configurer."""
        self._root_logger = logging.root
        self._root_logger.handlers.clear()

        logging.getLogger("uvicorn.access").disabled = True
        logging.getLogger("uvicorn.error").disabled = True

        self._hydrating_processors = cast(
            list[structlog.types.Processor],
            [
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.add_log_level,
                structlog.stdlib.add_logger_name,
            ],
        )

    def configure_console_logger(
        self, log_level: LogLevel, *, rich_rendering: bool
    ) -> None:
        """
        Configure the logging for the application.

        This function disables the default logging for uvicorn and sets up
        structlog with a specific configuration. The configuration includes
        merging context variables, adding log levels, rendering stack info,
        setting exception info, timestamping logs in ISO format with UTC,
        and rendering logs to the console.
        """
        if structlog.is_configured():
            return

        console_render_processors = [
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info
            if rich_rendering
            else structlog.processors.ExceptionRenderer(),
            structlog.dev.ConsoleRenderer()
            if rich_rendering
            else structlog.processors.LogfmtRenderer(),
        ]

        # Configure structlog
        # This applies to application logging (use structlog.get_logger()!)
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.stdlib.LoggerFactory(),
            processors=[
                *self._hydrating_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            cache_logger_on_first_use=True,
        )

        # Override root python logging
        # This primarily applies to third-party libraries
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *console_render_processors,
                ],
                foreign_pre_chain=self._hydrating_processors,
            )
        )
        self._root_logger.addHandler(handler)
        self._root_logger.setLevel(getattr(logging, log_level.upper()))

    def configure_otel_logger(self, handler: "LoggingHandler") -> None:
        """Configure the OpenTelemetry logger."""
        otel_render_processors = cast(
            list[structlog.types.Processor],
            [
                filter_otel_attributes,
                structlog.processors.ExceptionRenderer(
                    exception_formatter=structlog.tracebacks.ExceptionDictTransformer()
                ),
                structlog.processors.JSONRenderer(
                    sort_keys=True,
                    ensure_ascii=False,
                    indent=None,
                    separators=(",", ":"),
                ),
            ],
        )

        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *otel_render_processors,
                ],
                foreign_pre_chain=self._hydrating_processors,
            )
        )
        self._root_logger.addHandler(handler)


logger_configurer = LoggerConfigurer()
