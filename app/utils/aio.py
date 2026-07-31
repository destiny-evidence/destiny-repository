"""Utility functions for async iteration."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import TypeVar

T = TypeVar("T")


async def prefetch(source: AsyncGenerator[T, None]) -> AsyncGenerator[T, None]:
    """
    Yield from ``source`` with the next item already in flight.

    Overlaps a slow producer with a slow consumer: fetching item n+1 starts
    before the caller has finished with item n.

    Callers that may stop iterating early - via ``break``, or an exception in
    the loop body - must wrap this in :func:`contextlib.aclosing`.
    """
    upcoming = asyncio.ensure_future(anext(source))
    try:
        while True:
            try:
                item = await upcoming
            except StopAsyncIteration:
                return
            upcoming = asyncio.ensure_future(anext(source))
            yield item
    finally:
        upcoming.cancel()
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await upcoming
        await source.aclose()
