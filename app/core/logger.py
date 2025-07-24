"""Structured logging wrapper class."""

import logging
from collections.abc import MutableMapping

import structlog
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor


class Logger:
    """Structured logging wrapper class."""

    def __init__(self) -> None:
        """Initialize the logger."""
        self.logger = structlog.get_logger()

    def debug(self, message: str, **kwargs: dict) -> None:
        """Log a message with level DEBUG."""
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: dict) -> None:
        """Log a message with level INFO."""
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: dict) -> None:
        """Log a message with level WARNING."""
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: dict) -> None:
        """Log a message with level ERROR."""
        self.logger.error(message, **kwargs)

    def exception(self, message: str, **kwargs: dict) -> None:
        """
        Log a message with level ERROR.

        Exception info is added to the logging message.
        """
        self.logger.exception(message, **kwargs)


class TraceContextProcessor:
    """Add OpenTelemetry trace context to log records."""

    def __call__(
        self,
        _logger: object,
        _name: str,
        event_dict: MutableMapping[str, object],
    ) -> MutableMapping[str, object]:
        """Add trace context to the event dictionary."""
        span = trace.get_current_span()
        if span and span.is_recording():
            span_context = span.get_span_context()
            event_dict["trace_id"] = format(span_context.trace_id, "032x")
            event_dict["span_id"] = format(span_context.span_id, "016x")
        return event_dict


class NewlineKeyValueRenderer(structlog.processors.KeyValueRenderer):
    """
    Custom renderer to replace escaped newlines with real newlines.

    Enables the proper rendering of raw-text stack traces.
    """

    def __call__(
        self,
        logger: object,
        name: str,
        event_dict: MutableMapping[str, object],
    ) -> str:
        """Render log entry as key-value pairs."""
        # Call the base renderer
        rendered = super().__call__(logger, name, event_dict)
        # Replace escaped newlines in exception/stack fields with real newlines
        if isinstance(rendered, str):
            rendered = (
                rendered.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
            )
        return rendered


def configure_logger(*, rich_rendering: bool) -> None:
    """
    Configure the logging for the application.

    This function disables the default logging for uvicorn and sets up
    structlog with a specific configuration. The configuration includes
    merging context variables, adding log levels, rendering stack info,
    setting exception info, timestamping logs in ISO format with UTC,
    and rendering logs to the console.
    """
    # Configure OpenTelemetry logging instrumentation FIRST
    LoggingInstrumentor().instrument(set_logging_format=True)

    # Configure the root logger to ensure proper integration
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    # Disable uvicorn logging
    logging.getLogger("uvicorn.error").disabled = True
    logging.getLogger("uvicorn.access").disabled = True

    # Structlog configuration
    if rich_rendering:
        processors = [
            structlog.contextvars.merge_contextvars,
            TraceContextProcessor(),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            TraceContextProcessor(),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            NewlineKeyValueRenderer(),
        ]

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger() -> Logger:
    """Return a structured logger."""
    return Logger()
