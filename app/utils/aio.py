"""Utility functions for async iteration."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import Any, Final, TypeVar

T = TypeVar("T")

_DONE: Final = object()


async def prefetch(source: AsyncGenerator[T, None]) -> AsyncGenerator[T, None]:
    """
    Yield from ``source`` with the next item already in flight.

    Overlaps a slow producer with a slow consumer: fetching item n+1 starts
    before the caller has finished with item n.

    Callers that may stop iterating early - via ``break``, or an exception in
    the loop body - must wrap this in :func:`contextlib.aclosing`.
    """
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)

    async def _produce() -> None:
        try:
            async with contextlib.aclosing(source) as stream:
                async for item in stream:
                    await queue.put(item)
        except Exception as exc:  # noqa: BLE001 - re-raised in the consumer
            await queue.put(exc)
        else:
            await queue.put(_DONE)

    producer = asyncio.create_task(_produce())
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
