"""Structured logging wrapper class."""

import logging
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry import trace

from app.core.config import LogLevel

if TYPE_CHECKING:
    from opentelemetry.sdk._logs import LoggingHandler

_root_logger = logging.root


def add_open_telemetry_spans(
    _logger: Any,  # noqa: ANN401
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Add OpenTelemetry span information to the event dictionary."""
    span = trace.get_current_span()
    if not span.is_recording():
        event_dict["span"] = None
        return event_dict

    ctx = span.get_span_context()
    parent = getattr(span, "parent", None)

    event_dict["span"] = {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": None if not parent else format(parent.span_id, "016x"),
    }

    return event_dict


def _get_hydrating_processors() -> list[structlog.types.Processor]:
    """Get processors that hydrate the event dictionary."""
    return [
        structlog.contextvars.merge_contextvars,
        add_open_telemetry_spans,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
    ]


def configure_console_logger(log_level: LogLevel, *, rich_rendering: bool) -> None:
    """
    Configure the logging for the application.

    This function disables the default logging for uvicorn and sets up
    structlog with a specific configuration. The configuration includes
    merging context variables, adding log levels, rendering stack info,
    setting exception info, timestamping logs in ISO format with UTC,
    and rendering logs to the console.
    """
    for handler in _root_logger.handlers[:]:
        _root_logger.removeHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").disabled = False
    # logging.getLogger("elasticsearch").setLevel(logging.WARNING)
    # logging.getLogger("httpx").setLevel(logging.WARNING)

    console_render_processors = [
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info
        if rich_rendering
        else structlog.processors.ExceptionRenderer(),
        structlog.dev.ConsoleRenderer()
        if rich_rendering
        else structlog.processors.LogfmtRenderer(),
    ]

    # Globally configure
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        processors=[
            *_get_hydrating_processors(),
            *console_render_processors,
        ],
        cache_logger_on_first_use=True,
    )

    # Override root python logging
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            *_get_hydrating_processors(),
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *console_render_processors,
        ]
    )

    # Add our custom handler
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    _root_logger.addHandler(handler)
    _root_logger.setLevel(getattr(logging, log_level.upper()))


def configure_otel_logger(handler: "LoggingHandler") -> None:
    """Configure the OpenTelemetry logger."""
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                *_get_hydrating_processors(),
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
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
    )
    _root_logger.addHandler(handler)
