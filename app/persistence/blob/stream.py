"""A module to stream data from a function asynchronously."""

from asyncio import gather
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from io import BytesIO
from typing import Any

from app.domain.base import SDKJsonlMixin


class FileStream:
    """
    A helper class to convert a service function into an asynchronous file stream.

    This allows memory-efficient streaming of data from a function that returns a list
    of objects that inherit from SDKJsonlMixin. This inheritance is important as it
    highlights that the full flow of data has been considered through to the user.
    """

    def __init__(
        self,
        fn: Callable[..., Awaitable[list[SDKJsonlMixin]]],
        fn_kwargs: Sequence[dict[str, Any]],
    ) -> None:
        """
        Initialize the FileStream with a function and its arguments.

        :param fn: The function to call.
        :type fn: Callable[..., Awaitable[list[SDKJsonlMixin]]]
        :param fn_kwargs: A sequence of dicts of arguments to pass to the function.
            These should match the kwargs of the function. Chunking is the
            responsibility of the caller, as this class cannot know what arguments
            expect chunked lists.
        :type fn_kwargs: Sequence[dict[str, Any]]
        """
        self.fn = fn
        self.fn_kwargs = fn_kwargs

    async def stream(self) -> AsyncGenerator[bytes, None]:
        """Asynchronously read data from the function."""
        for kwargs in self.fn_kwargs:
            data = await self.fn(**kwargs)
            converted = [item.to_sdk().to_jsonl() + "\n" for item in data]
            yield "".join(converted).encode("utf-8")

    async def read(self) -> BytesIO:
        """
        Read all data from the function and return as a file-like object.

        For implementations where async generators are not supported we read all data
        into memory and return a BytesIO object. Currently this applied only to minio
        which is only used for local and testing purposes. If this becomes a bottleneck
        we can also look into composing blobs: https://min.io/docs/minio/linux/developers/python/API.html#compose_object
        """
        data = await gather(*[self.fn(**kwargs) for kwargs in self.fn_kwargs])
        buffer = BytesIO()
        for chunk in data:
            buffer.write(
                "".join(item.to_sdk().to_jsonl() + "\n" for item in chunk).encode(
                    "utf-8"
                )
            )
        buffer.seek(0)
        return buffer
