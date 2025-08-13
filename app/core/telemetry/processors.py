"""Processors for OpenTelemetry data."""

from collections.abc import Callable
from typing import ClassVar

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span
from opentelemetry.sdk.trace.export import BatchSpanProcessor

T_condition = Callable[[ReadableSpan], bool]


class FilteringBatchSpanProcessor(BatchSpanProcessor):
    """Filters spans based on given conditions."""

    _conditions: ClassVar[list[T_condition]] = []

    def add_condition(self, condition: T_condition) -> None:
        """Add a condition to filter spans."""
        self._conditions.append(condition)

    def _filter_condition(self, span: ReadableSpan) -> bool:
        """Return True if the span matches any condition."""
        return any(condition(span) for condition in self._conditions)

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Override to filter spans on start."""
        if self._filter_condition(span):
            return
        super().on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        """Override to filter spans on end."""
        if self._filter_condition(span):
            return
        super().on_end(span)
