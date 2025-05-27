"""A module to stream data from a function asynchronously."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
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
        fn_args: Sequence[dict[str, Any]],
    ) -> None:
        """
        Initialize the FileStream with a function and its arguments.

        :param fn: The function to call.
        :type fn: Callable[..., Awaitable[list[SDKJsonlMixin]]]
        :param fn_args: A sequence of dicts of arguments to pass to the function. These
            should match the kwargs of the function. Chunking is the responsibility of
            the caller, as this class cannot know what arguments expect chunked lists.
        :type fn_args: Sequence[dict[str, Any]]
        """
        self.fn = fn
        self.fn_args = fn_args

    async def read(self) -> AsyncGenerator[bytes, None]:
        """Asynchronously read data from the function."""
        for args in self.fn_args:
            data = await self.fn(**args)
            yield "\n".join(item.to_sdk().to_jsonl() for item in data).encode("utf-8")
