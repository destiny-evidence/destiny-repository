"""Functionality for OpenTelemetry tracing with Taskiq."""

from __future__ import annotations

import contextvars
import importlib
from typing import TYPE_CHECKING, Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, SpanKind
from structlog.contextvars import bind_contextvars, clear_contextvars
from taskiq import (
    AsyncTaskiqDecoratedTask,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)

from app.core.config import get_settings
from app.core.telemetry.attributes import Attributes
from app.core.telemetry.logger import get_logger

if TYPE_CHECKING:
    from opentelemetry.context import Context

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)
settings = get_settings()


async def queue_task_with_trace(
    task: AsyncTaskiqDecoratedTask | tuple[str, str],
    *args: object,
    renew_lock: bool = False,
    **kwargs: object,
) -> None:
    """
    Wrap around taskiq queueing to inject OpenTelemetry trace context.

    All tasks should be queued through this function to ensure
    that the OpenTelemetry trace context is automatically injected.
    """
    # Allow runtime string imports so services can queue tasks without circular imports
    if isinstance(task, tuple):
        imported_module = importlib.import_module(task[0])
        imported_task = getattr(imported_module, task[1])
        if not isinstance(imported_task, AsyncTaskiqDecoratedTask):
            msg = "String path must resolve to an AsyncTaskiqDecoratedTask"
            raise TypeError(msg)
        task = imported_task

    task.labels["renew_lock"] = renew_lock

    logger.info(
        "Queueing task",
        task_name=task.task_name,
        **{k: str(v) for k, v in kwargs.items()},
    )
    if not settings.otel_enabled:
        # If OpenTelemetry is not enabled, just queue the task normally
        await task.kiq(*args, **kwargs)
        return
    with tracer.start_as_current_span(
        f"queue.{task.task_name}",
        kind=SpanKind.PRODUCER,
        attributes={
            Attributes.MESSAGING_DESTINATION_NAME: task.task_name,
            Attributes.MESSAGING_OPERATION: "send",
            Attributes.MESSAGING_SYSTEM: "taskiq",
        },
    ):
        # Inject the current trace context into the message carrier
        # for distributed tracing
        carrier: dict[str, Any] = {}
        propagate.inject(carrier)
        # Queue the task with the trace context
        await task.kiq(
            *args,
            **kwargs,
            trace_context=carrier,
        )


class TaskiqTracingMiddleware(TaskiqMiddleware):
    """
    Custom TaskIQ middleware for OpenTelemetry tracing.

    This middleware automatically extracts trace context from incoming messages
    and creates spans for task execution, providing seamless distributed tracing
    across the task queue.

    Uses contextvars for thread-safe span and context management in concurrent
    task execution environments.
    """

    def __init__(self) -> None:
        """Initialize the middleware with context variables for concurrency safety."""
        super().__init__()
        # Use contextvars for thread-safe state management across concurrent tasks
        self._current_span: contextvars.ContextVar[Span | None] = (
            contextvars.ContextVar("taskiq_current_span", default=None)
        )
        self._token: contextvars.ContextVar[context.Token[Context] | None] = (
            contextvars.ContextVar("taskiq_context_token", default=None)
        )

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """
        Extract trace context and start a span before task execution.

        Args:
            message: The incoming TaskIQ message

        Returns:
            The message with trace context removed.

        """
        # Extract trace context from message kwargs
        carrier: dict[str, Any] = {}
        if (
            hasattr(message, "kwargs")
            and message.kwargs
            and "trace_context" in message.kwargs
        ):
            carrier = message.kwargs.pop("trace_context", {})
            bind_contextvars(**{k: str(v) for k, v in message.kwargs.items()})

        bind_contextvars(task_name=message.task_name)
        logger.debug(
            "Received task with trace context",
            carrier_keys=list(carrier.keys()),
        )

        # Let OpenTelemetry extract the context
        ctx = propagate.extract(carrier)

        # Start a new span for the task execution using the extracted context
        current_span = tracer.start_span(
            f"execute.{message.task_name}",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                Attributes.MESSAGING_DESTINATION_NAME: message.task_name,
                Attributes.MESSAGING_MESSAGE_ID: message.task_id,
                Attributes.MESSAGING_OPERATION: "receive",
                Attributes.MESSAGING_SYSTEM: "taskiq",
            },
        )
        # Store the span in context variable for this task
        self._current_span.set(current_span)

        # Activate the context for this span during task execution
        token = context.attach(trace.set_span_in_context(current_span))
        self._token.set(token)

        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult[Any]
    ) -> None:
        """
        Complete the span after task execution.

        Args:
            message: The TaskIQ message that was executed
            result: The result of the task execution

        """
        current_span = self._current_span.get(None)
        if current_span:
            try:
                if result.is_err:
                    # Task failed - record the error
                    current_span.set_status(
                        trace.Status(trace.StatusCode.ERROR, str(result.error))
                    )
                    if result.error:
                        current_span.record_exception(result.error)
                else:
                    # Task succeeded
                    current_span.set_status(trace.Status(trace.StatusCode.OK))

                # End the span
                current_span.end()

                logger.debug(
                    "Completed OpenTelemetry span for task",
                    task_id=message.task_id,
                    success=not result.is_err,
                )

            finally:
                # Clear the span from context variable
                self._current_span.set(None)

                # Detach the context
                token = self._token.get(None)
                if token:
                    context.detach(token)
                    self._token.set(None)
        clear_contextvars()
