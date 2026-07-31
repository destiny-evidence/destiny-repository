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
async def test_prefetch_reads_at_most_one_ahead():
    produced: list[int] = []
    seen: list[int] = []

    async for item in prefetch(_slow_source(6, 0, produced)):
        await asyncio.sleep(0)
        seen.append(item)
        # Only the immediate successor may have been fetched.
        assert len(produced) <= len(seen) + 1

    assert seen == [0, 1, 2, 3, 4, 5]


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
