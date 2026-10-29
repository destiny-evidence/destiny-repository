"""Tests for span helpers."""

from collections.abc import Callable

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import StatusCode

from app.core.telemetry.attributes import start_span_passing


class _ExpectedError(Exception):
    pass


def test_a_passing_exception_leaves_the_span_unerrored(
    finished_span: Callable[[str], ReadableSpan],
) -> None:
    """An expected exception propagates without error status or event."""
    tracer = trace.get_tracer(__name__)

    with (
        pytest.raises(_ExpectedError),
        start_span_passing(tracer, "work", passing=(_ExpectedError,)),
    ):
        raise _ExpectedError

    span = finished_span("work")
    assert span.status.status_code is StatusCode.UNSET
    assert span.events == ()


def test_any_other_exception_still_errors_the_span(
    finished_span: Callable[[str], ReadableSpan],
) -> None:
    """Every other exception is recorded as it would be by default."""
    tracer = trace.get_tracer(__name__)

    with (
        pytest.raises(RuntimeError),
        start_span_passing(tracer, "work", passing=(_ExpectedError,)),
    ):
        raise RuntimeError("boom")  # noqa: EM101

    span = finished_span("work")
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "RuntimeError: boom"
    assert [event.name for event in span.events] == ["exception"]
