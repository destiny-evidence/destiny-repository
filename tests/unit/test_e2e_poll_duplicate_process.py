"""Unit tests for the e2e ``poll_duplicate_process`` helper's polling budget.

These pin the elapsed-time polling contract that keeps the deduplication e2e
tests reliable: the dedup task retries the active-decision constraint collision,
during which a reference transiently has no active decision, and recovery can
outlast a fixed short attempt count.

The clock and sleep are mocked so the assertions are deterministic: a flake fix
whose own tests depended on wall-clock timing would defeat the purpose.
"""

import types
from uuid import uuid7

import pytest
from sqlalchemy.exc import NoResultFound

from tests.e2e import utils
from tests.e2e.utils import TestPollingExhaustedError, poll_duplicate_process

_MISSING = object()


async def _noop_sleep(*_args: object, **_kwargs: object) -> None:
    """Stand in for asyncio.sleep so polling advances without real waiting."""


class _FakeClock:
    """Monotonic-clock stand-in returning each scripted reading, then the last."""

    def __init__(self, readings: list[float]) -> None:
        self._readings = readings
        self._index = 0

    def __call__(self) -> float:
        reading = self._readings[min(self._index, len(self._readings) - 1)]
        self._index += 1
        return reading


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        if self._value is _MISSING:
            raise NoResultFound
        return self._value


class _FakeSession:
    """Minimal AsyncSession stand-in yielding no row until ``appear_on_call``."""

    def __init__(self, *, appear_on_call: int, value: object) -> None:
        self._appear_on_call = appear_on_call
        self._value = value
        self.calls = 0

    async def execute(self, _query: object) -> _FakeResult:
        self.calls += 1
        if self.calls >= self._appear_on_call:
            return _FakeResult(self._value)
        return _FakeResult(_MISSING)


def _mock_clock_and_sleep(monkeypatch: pytest.MonkeyPatch, monotonic: object) -> None:
    monkeypatch.setattr(utils, "asyncio", types.SimpleNamespace(sleep=_noop_sleep))
    monkeypatch.setattr(utils, "time", types.SimpleNamespace(monotonic=monotonic))


async def test_poll_returns_decision_that_settles_after_old_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decision appearing past the former five-attempt budget is still returned."""
    _mock_clock_and_sleep(monkeypatch, monotonic=lambda: 0.0)  # deadline never elapses
    decision = object()
    session = _FakeSession(appear_on_call=8, value=decision)

    result = await poll_duplicate_process(session, uuid7(), timeout_seconds=20.0)

    assert result is decision
    assert session.calls == 8


async def test_poll_times_out_on_elapsed_budget_not_fixed_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no decision settles, it polls until the budget elapses, then raises."""
    # First reading sets the deadline; the budget is then reached on the third check.
    _mock_clock_and_sleep(monkeypatch, monotonic=_FakeClock([0.0, 0.0, 0.0, 1.0]))
    session = _FakeSession(appear_on_call=10**9, value=object())

    with pytest.raises(TestPollingExhaustedError):
        await poll_duplicate_process(session, uuid7(), timeout_seconds=1.0)

    assert session.calls == 3
