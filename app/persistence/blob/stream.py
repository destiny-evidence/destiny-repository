"""A module to stream data from a function asynchronously."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from app.domain.base import SDKJsonlMixin


class FileStream:
    """A helper class to convert a service function into an asynchronous file stream."""

    def __init__(
        self,
        fn: Callable[..., Awaitable[list[SDKJsonlMixin]]],
        fn_args: list[dict[str, Any]],
    ) -> None:
        """Initialize the FileStream with a function and its arguments."""
        self.fn = fn
        self.fn_args = fn_args

    async def read(self) -> AsyncGenerator[bytes, None]:
        """Asynchronously read data from the function."""
        for args in self.fn_args:
            data = await self.fn(**args)
            yield "\n".join(item.to_sdk().to_jsonl() for item in data).encode("utf-8")  # type: ignore[attr-defined]
