"""Functionality for OpenTelemetry tracing with Taskiq."""

from __future__ import annotations

import contextvars
import importlib
from typing import Any

from opentelemetry import context, trace
from opentelemetry.trace import Link, Span, SpanContext, SpanKind
from structlog.contextvars import bind_contextvars, clear_contextvars
from taskiq import (
    AsyncTaskiqDecoratedTask,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)

from app.core.telemetry.attributes import Attributes
from app.core.telemetry.logger import get_logger

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


async def queue_task_with_trace(
    task: AsyncTaskiqDecoratedTask | tuple[str, str],
    *args: object,
    long_running: bool = False,
    otel_enabled: bool,
    **kwargs: object,
) -> None:
    """
    Wrap around taskiq queueing to pass OpenTelemetry trace link.

    :param task: The TaskIQ task to queue or a tuple of (module_path, task_name).
    :type task: AsyncTaskiqDecoratedTask | tuple[str, str]
    :param args: Positional arguments for the task.
    :type args: object
    :param long_running: Whether the task is long-running and needs lock renewal.
    :type long_running: bool
    :param kwargs: Keyword arguments for the task.
    :type kwargs: object

    All tasks should be queued through this function to ensure trace linking.
    Tasks create their own traces with a link back to the producer span for correlation.
    """
    # Allow runtime string imports so services can queue tasks without circular imports
    if isinstance(task, tuple):
        imported_module = importlib.import_module(task[0])
        imported_task = getattr(imported_module, task[1])
        if not isinstance(imported_task, AsyncTaskiqDecoratedTask):
            msg = "String path must resolve to an AsyncTaskiqDecoratedTask"
            raise TypeError(msg)
        task = imported_task

    task.labels["renew_lock"] = long_running

    logger.info(
        "Queueing task",
        task_name=task.task_name,
        **{k: str(v) for k, v in kwargs.items()},
    )
    if not otel_enabled:
        # If OpenTelemetry is not enabled, just queue the task normally
        await task.kiq(*args, **kwargs)
        return

    # Pass span context for linking (not propagation) so tasks
    # create their own traces with independent sampling decisions
    span_context = trace.get_current_span().get_span_context()
    trace_link = {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }
    await task.kiq(
        *args,
        **kwargs,
        trace_link=trace_link,
    )


class TaskiqTracingMiddleware(TaskiqMiddleware):
    """
    Custom TaskIQ middleware for OpenTelemetry tracing.

    This middleware creates independent traces for each task execution with
    links back to the producer span.

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
        self._token: contextvars.ContextVar[context.Token[context.Context] | None] = (
            contextvars.ContextVar("taskiq_context_token", default=None)
        )

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """
        Extract trace link and start a new trace for task execution.

        Args:
            message: The incoming TaskIQ message

        Returns:
            The message with trace link removed.

        """
        # Extract trace link from message kwargs (for linking, not parenting)
        links: list[Link] = []
        if (
            hasattr(message, "kwargs")
            and message.kwargs
            and "trace_link" in message.kwargs
        ):
            trace_link = message.kwargs.pop("trace_link", {})
            bind_contextvars(**{k: str(v) for k, v in message.kwargs.items()})

            if trace_link:
                # Create a link to the producer span for trace correlation
                linked_context = SpanContext(
                    trace_id=int(trace_link["trace_id"], 16),
                    span_id=int(trace_link["span_id"], 16),
                    is_remote=True,
                )
                links.append(Link(linked_context))

        bind_contextvars(task_name=message.task_name)
        logger.debug(
            "Received task with trace link",
            has_link=len(links) > 0,
        )

        # Start a new root span (no parent context) with link to producer
        # This creates an independent trace for tail-based sampling
        current_span = tracer.start_span(
            f"execute.{message.task_name}",  # NB actual task will rename the span
            kind=SpanKind.CONSUMER,
            links=links,
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
