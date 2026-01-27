"""Tests for the Taskiq tracing middleware."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.trace import Link, SpanContext, SpanKind
from taskiq import TaskiqMessage, TaskiqResult

from app.core.telemetry.taskiq import TaskiqTracingMiddleware


@pytest.mark.asyncio
async def test_trace_link_creates_independent_trace():
    """Test that trace link creates a new trace with link to producer span."""
    middleware = TaskiqTracingMiddleware()

    with (
        patch("app.core.telemetry.taskiq.tracer") as mock_tracer,
        patch("app.core.telemetry.taskiq.context") as mock_context,
    ):
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        mock_token = MagicMock()
        mock_context.attach.return_value = mock_token

        # Trace link format: hex-encoded trace_id and span_id
        trace_link = {
            "trace_id": "0" * 32,  # 128-bit trace ID as 32 hex chars
            "span_id": "0" * 16,  # 64-bit span ID as 16 hex chars
        }
        message = TaskiqMessage(
            task_id="test-task",
            task_name="test_task",
            args=(),
            kwargs={"trace_link": trace_link, "other_arg": "value"},
            labels={},
        )

        processed_message = await middleware.pre_execute(message)

        # trace_link should be removed from kwargs
        assert "trace_link" not in processed_message.kwargs
        assert processed_message.kwargs["other_arg"] == "value"

        # Verify start_span was called with links (not context)
        mock_tracer.start_span.assert_called_once()
        call_kwargs = mock_tracer.start_span.call_args.kwargs

        # Should NOT have context (independent trace)
        assert "context" not in call_kwargs

        # Should have links to producer span
        assert "links" in call_kwargs
        links = call_kwargs["links"]
        assert len(links) == 1
        assert isinstance(links[0], Link)

        # Verify the linked SpanContext
        linked_ctx = links[0].context
        assert isinstance(linked_ctx, SpanContext)
        assert linked_ctx.trace_id == 0
        assert linked_ctx.span_id == 0
        assert linked_ctx.is_remote is True

        # Verify span kind is CONSUMER
        assert call_kwargs["kind"] == SpanKind.CONSUMER

        mock_context.attach.assert_called_once()

        result = TaskiqResult(
            is_err=False, error=None, return_value="success", execution_time=0.01
        )
        await middleware.post_execute(message, result)

        mock_context.detach.assert_called_once_with(mock_token)


@pytest.mark.asyncio
async def test_no_trace_link_creates_unlinked_trace():
    """Test that missing trace_link creates a trace with no links."""
    middleware = TaskiqTracingMiddleware()

    with (
        patch("app.core.telemetry.taskiq.tracer") as mock_tracer,
        patch("app.core.telemetry.taskiq.context") as mock_context,
    ):
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        mock_context.attach.return_value = MagicMock()

        message = TaskiqMessage(
            task_id="test-task",
            task_name="test_task",
            args=(),
            kwargs={"other_arg": "value"},
            labels={},
        )

        await middleware.pre_execute(message)

        mock_tracer.start_span.assert_called_once()
        call_kwargs = mock_tracer.start_span.call_args.kwargs

        # Should have empty links list
        assert call_kwargs["links"] == []


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
