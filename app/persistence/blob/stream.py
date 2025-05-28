"""A module to stream data from a function asynchronously."""

from asyncio import gather
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from io import BytesIO
from typing import Any, TypeVar

from app.domain.base import SDKJsonlMixin

Streamable = TypeVar(
    "Streamable", bound=SDKJsonlMixin | str | list[SDKJsonlMixin] | list[str]
)


class FileStream:
    """
    A helper class to convert a service function or generator into an async file stream.

    This allows memory-efficient streaming of data from a function that returns a list
    of objects that inherit from SDKJsonlMixin, or from an async generator that yields
    strings.
    """

    def __init__(
        self,
        fn: Callable[..., Awaitable[Streamable]] | None = None,
        fn_kwargs: Sequence[dict[str, Any]] | None = None,
        generator: AsyncGenerator[Streamable, None] | None = None,
    ) -> None:
        """
        Initialize the FileStream with a function and its arguments or a generator.

        A function or a generator must be provided, but not both.

        :param fn: The function to call.
        :type fn: Callable[..., Awaitable[Streamable]] | None
        :param fn_kwargs: A sequence of dicts of arguments to pass to the function.
        :type fn_kwargs: Sequence[dict[str, Any]]
        :param generator: An async generator yielding Streamable.
        :type generator: AsyncGenerator[Streamable, None] | None
        """
        self.fn = fn
        self.fn_kwargs = fn_kwargs or []
        self.generator = generator

    def _to_str(self, data: Streamable) -> str:
        """Convert a Streamable object to a string."""
        if isinstance(data, list):
            return "".join(self._to_str(item) for item in data)
        return (
            data.to_sdk().to_jsonl() if isinstance(data, SDKJsonlMixin) else data
        ) + "\n"

    def _to_bytes(self, data: Streamable) -> bytes:
        """Convert a Streamable object to bytes."""
        b = self._to_str(data)
        return b.encode("utf-8")

    async def stream(self) -> AsyncGenerator[bytes, None]:
        """Asynchronously read data from the function or generator."""
        if self.generator:
            async for chunk in self.generator:
                yield self._to_bytes(chunk)
        elif self.fn:
            for kwargs in self.fn_kwargs:
                data = await self.fn(**kwargs)
                yield self._to_bytes(data)

    async def read(self) -> BytesIO:
        """
        Read all data from the function or generator and return as a file-like object.

        For implementations where async generators are not supported we read all data
        into memory and return a BytesIO object. Currently this applied only to minio
        which is only used for local and testing purposes. If this becomes a problem
        we can also look into composing blobs: https://min.io/docs/minio/linux/developers/python/API.html#compose_object
        """
        buffer = BytesIO()
        if self.generator:
            async for chunk in self.generator:
                buffer.write(self._to_bytes(chunk))
        elif self.fn:
            data = await gather(*[self.fn(**kwargs) for kwargs in self.fn_kwargs])
            for chunk in data:
                buffer.write(self._to_bytes(chunk))
        buffer.seek(0)
        return buffer
