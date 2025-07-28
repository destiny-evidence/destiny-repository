"""Functionality for OpenTelemetry tracing with Taskiq."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, SpanKind
from taskiq import (
    AsyncTaskiqDecoratedTask,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)

from app.core.logger import get_logger
from app.core.telemetry.semconv import SemConv

if TYPE_CHECKING:
    from opentelemetry.context import Context

tracer = trace.get_tracer(__name__)
logger = get_logger()


class TaskiqTracingMiddleware(TaskiqMiddleware):
    """
    Custom TaskIQ middleware for OpenTelemetry tracing.

    This middleware automatically extracts trace context from incoming messages
    and creates spans for task execution, providing seamless distributed tracing
    across the task queue.
    """

    def __init__(self) -> None:
        """Initialize the middleware."""
        super().__init__()
        self._current_span: Span | None = None
        self._token: context.Token[Context] | None = None

    @staticmethod
    async def kiq(
        task: AsyncTaskiqDecoratedTask,
        *args: object,
        **kwargs: object,
    ) -> None:
        """
        Wrap around taskiq queueing to inject OpenTelemetry trace context.

        All tasks should be queued through this function to ensure
        that the OpenTelemetry trace context is automatically injected.
        """
        with tracer.start_as_current_span(
            f"queue.{task.task_name}",
            kind=SpanKind.PRODUCER,
            attributes={
                SemConv.MESSAGING_DESTINATION_NAME: task.task_name,
                SemConv.MESSAGING_OPERATION: "send",
                SemConv.MESSAGING_SYSTEM: "taskiq",
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

        logger.debug(
            "Received task with trace context",
            extra={
                "task_name": message.task_name,
                "carrier_keys": list(carrier.keys()),
            },
        )

        # Let OpenTelemetry extract the context
        ctx = propagate.extract(carrier)

        # Start a new span for the task execution using the extracted context
        self._current_span = tracer.start_span(
            f"execute.{message.task_name}",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                SemConv.MESSAGING_DESTINATION_NAME: message.task_name,
                SemConv.MESSAGING_MESSAGE_ID: message.task_id,
                SemConv.MESSAGING_OPERATION: "receive",
                SemConv.MESSAGING_SYSTEM: "taskiq",
            },
        )
        # Activate the context for this span during task execution
        self._token = context.attach(trace.set_span_in_context(self._current_span))

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
        if self._current_span:
            try:
                if result.is_err:
                    # Task failed - record the error
                    self._current_span.set_status(
                        trace.Status(trace.StatusCode.ERROR, str(result.error))
                    )
                    if result.error:
                        self._current_span.record_exception(result.error)
                else:
                    # Task succeeded
                    self._current_span.set_status(trace.Status(trace.StatusCode.OK))

                # End the span
                self._current_span.__exit__(None, None, None)

                logger.debug(
                    "Completed OpenTelemetry span for task",
                    extra={
                        "task_name": message.task_name,
                        "task_id": message.task_id,
                        "success": not result.is_err,
                    },
                )

            finally:
                self._current_span = None

                # Detach the context
                if self._token:
                    context.detach(self._token)
                    self._token = None
