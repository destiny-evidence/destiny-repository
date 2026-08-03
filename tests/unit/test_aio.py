import asyncio
import contextlib
import contextvars

import pytest

from app.utils.aio import prefetch


async def _slow_source(n, delay, produced=None):
    for i in range(n):
        await asyncio.sleep(delay)
        if produced is not None:
            produced.append(i)
        yield i


async def _closeable(closed):
    try:
        for i in range(100):
            yield i
    finally:
        closed.set()


@pytest.mark.asyncio
async def test_prefetch_advances_source_in_one_context():
    """The source must be resumed from a single task."""
    var = contextvars.ContextVar("probe", default=0)

    async def _instrumented():
        token = var.set(1)
        try:
            for i in range(5):
                yield i
        finally:
            var.reset(token)

    assert [item async for item in prefetch(_instrumented())] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_prefetch_closes_source_in_one_context_on_early_break():
    """The same holds when the close happens while the fetch is being cancelled."""
    var = contextvars.ContextVar("probe", default=0)
    closed = asyncio.Event()

    async def _instrumented():
        token = var.set(1)
        try:
            for i in range(100):
                await asyncio.sleep(0)
                yield i
        finally:
            var.reset(token)
            closed.set()

    async with contextlib.aclosing(prefetch(_instrumented())) as items:
        async for item in items:
            if item == 2:
                break

    assert closed.is_set()


@pytest.mark.asyncio
async def test_prefetch_preserves_order_and_completes():
    assert [item async for item in prefetch(_slow_source(5, 0))] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_prefetch_overlaps_producer_and_consumer():
    """Serial iteration costs n*(produce+consume); prefetched, the two overlap."""
    delay = 0.02
    n = 5

    start = asyncio.get_running_loop().time()
    async for _ in prefetch(_slow_source(n, delay)):
        await asyncio.sleep(delay)
    elapsed = asyncio.get_running_loop().time() - start

    serial = 2 * n * delay
    assert elapsed < serial * 0.8


@pytest.mark.asyncio
async def test_prefetch_lookahead_is_bounded_at_two():
    """
    A slow consumer leaves the source two items ahead, and no further.

    One item waits in the queue while the producer holds a second, blocked on
    putting it.
    """
    produced: list[int] = []
    seen: list[int] = []
    lookaheads: list[int] = []

    async for item in prefetch(_slow_source(8, 0.001, produced)):
        await asyncio.sleep(0.01)
        seen.append(item)
        lookaheads.append(len(produced) - len(seen))

    assert seen == [0, 1, 2, 3, 4, 5, 6, 7]
    assert max(lookaheads) == 2


@pytest.mark.asyncio
async def test_prefetch_propagates_cancellation_of_the_consumer():
    consuming = asyncio.Event()

    async def _consume():
        async with contextlib.aclosing(prefetch(_slow_source(100, 0.01))) as items:
            async for _ in items:
                consuming.set()
                await asyncio.sleep(10)

    task = asyncio.create_task(_consume())
    await consuming.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_prefetch_propagates_cancellation_arriving_during_cleanup():
    """
    Awaiting the producer must not absorb a cancellation of the consumer.

    Tearing the producer down is expected to raise CancelledError, but that
    same await is a delivery point for the consumer's own cancellation. If it
    is swallowed, a worker asked to stop carries on to the next statement.
    """
    closing = asyncio.Event()

    async def _slow_to_close():
        try:
            for i in range(100):
                yield i
        finally:
            closing.set()
            await asyncio.sleep(0.2)

    async def _consume():
        async with contextlib.aclosing(prefetch(_slow_to_close())) as items:
            async for item in items:
                if item == 0:
                    break

    task = asyncio.create_task(_consume())
    await closing.wait()
    await asyncio.sleep(0)  # let the consumer reach `await producer`
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


class _Fatal(BaseException):
    """Stands in for SystemExit/KeyboardInterrupt without tripping pytest."""


@pytest.mark.asyncio
async def test_prefetch_propagates_base_exception_from_source():
    """A BaseException reaches the consumer instead of stranding it."""

    async def _fatal():
        yield 0
        raise _Fatal

    async def _drain():
        async for _ in prefetch(_fatal()):
            pass

    # It must arrive promptly. A stranded consumer also surfaces _Fatal, but
    # only once something else cancels it and the finally re-raises it off the
    # dead producer - in production, nothing would.
    start = asyncio.get_running_loop().time()
    with pytest.raises(_Fatal):
        await asyncio.wait_for(_drain(), timeout=2)

    assert asyncio.get_running_loop().time() - start < 0.5


@pytest.mark.asyncio
async def test_prefetch_propagates_source_error():
    async def _failing():
        yield 0
        msg = "boom"
        raise ValueError(msg)

    seen = []

    async def _drain():
        async for item in prefetch(_failing()):
            seen.append(item)  # noqa: PERF401 - must survive the raise

    with pytest.raises(ValueError, match="boom"):
        await _drain()

    assert seen == [0]


@pytest.mark.asyncio
async def test_prefetch_closes_source_on_early_break():
    closed = asyncio.Event()

    async with contextlib.aclosing(prefetch(_closeable(closed))) as pages:
        async for item in pages:
            if item == 2:
                break

    assert closed.is_set()


@pytest.mark.asyncio
async def test_prefetch_closes_source_when_consumer_raises():
    closed = asyncio.Event()

    async def _fail_in_body():
        async with contextlib.aclosing(prefetch(_closeable(closed))) as pages:
            async for _ in pages:
                msg = "consumer failed"
                raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="consumer failed"):
        await _fail_in_body()

    assert closed.is_set()
