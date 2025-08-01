"""Tests for the Taskiq tracing middleware."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from taskiq import TaskiqMessage, TaskiqResult

from app.core.telemetry.taskiq import TaskiqTracingMiddleware


@pytest.mark.asyncio
async def test_trace_context_propagation():
    """Test that trace context is properly extracted and propagated."""
    middleware = TaskiqTracingMiddleware()

    with (
        patch("app.core.telemetry.taskiq.tracer") as mock_tracer,
        patch("app.core.telemetry.taskiq.propagate") as mock_propagate,
        patch("app.core.telemetry.taskiq.context") as mock_context,
    ):
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        mock_ctx = MagicMock()
        mock_propagate.extract.return_value = mock_ctx
        mock_token = MagicMock()
        mock_context.attach.return_value = mock_token

        trace_context = {"traceparent": "00-trace123-span456-01"}
        message = TaskiqMessage(
            task_id="test-task",
            task_name="test_task",
            args=(),
            kwargs={"trace_context": trace_context, "other_arg": "value"},
            labels={},
        )

        processed_message = await middleware.pre_execute(message)

        mock_propagate.extract.assert_called_once_with(trace_context)

        assert "trace_context" not in processed_message.kwargs
        assert processed_message.kwargs["other_arg"] == "value"

        mock_tracer.start_span.assert_called_once()
        call_kwargs = mock_tracer.start_span.call_args.kwargs
        assert call_kwargs["context"] is mock_ctx

        mock_context.attach.assert_called_once()

        result = TaskiqResult(
            is_err=False, error=None, return_value="success", execution_time=0.01
        )
        await middleware.post_execute(message, result)

        mock_context.detach.assert_called_once_with(mock_token)


@pytest.mark.asyncio
async def test_context_isolation_between_tasks():
    """Test that context variables are properly isolated between concurrent tasks."""
    middleware = TaskiqTracingMiddleware()

    with patch("app.core.telemetry.taskiq.tracer") as mock_tracer:
        span_a = MagicMock()
        span_b = MagicMock()
        mock_tracer.start_span.side_effect = [span_a, span_b]

        # Track which span each task sees during execution
        spans_seen = {}

        async def task_with_context_check(
            task_id: str, message: TaskiqMessage
        ) -> MagicMock:
            """Task that checks which span is in its context during execution."""
            await middleware.pre_execute(message)

            current_span = middleware._current_span.get(None)  # noqa: SLF001
            spans_seen[task_id] = current_span

            # Simulate some work
            await asyncio.sleep(1)

            # Verify the span hasn't changed during execution
            assert middleware._current_span.get(None) is current_span  # noqa: SLF001

            # Complete the task
            result: TaskiqResult = TaskiqResult(
                is_err=False,
                error=None,
                return_value=f"done-{task_id}",
                execution_time=1,
            )
            await middleware.post_execute(message, result)

            return current_span

        # Create messages
        message_a = TaskiqMessage(
            task_id="task-a", task_name="test_task_a", args=(), kwargs={}, labels={}
        )

        message_b = TaskiqMessage(
            task_id="task-b", task_name="test_task_b", args=(), kwargs={}, labels={}
        )

        # Run tasks concurrently
        await asyncio.gather(
            task_with_context_check("task-a", message_a),
            task_with_context_check("task-b", message_b),
        )

        # Verify each task saw a different span
        assert spans_seen["task-a"] is span_a
        assert spans_seen["task-b"] is span_b
        assert spans_seen["task-a"] is not spans_seen["task-b"]

        # Verify both spans were properly cleaned up
        span_a.end.assert_called_once()
        span_b.end.assert_called_once()
