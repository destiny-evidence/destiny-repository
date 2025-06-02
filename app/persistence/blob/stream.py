"""A module to stream data from a function asynchronously."""

from asyncio import gather
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from io import BytesIO
from typing import Any, TypeVar

from app.core.exceptions import BlobStorageError
from app.domain.base import SDKJsonlMixin

Streamable = TypeVar(
    "Streamable", bound=SDKJsonlMixin | str | list[SDKJsonlMixin] | list[str]
)


class FileStream:
    """
    A helper class to convert a service function or generator into an async file stream.

    This allows memory-efficient streaming of data from a function that returns a list
    of objects that inherit from :class:`app.domain.base.SDKJsonlMixin`, which
    identifies domain models that can be converted to JSONL format, or from an async
    generator that yields strings.

    Example usage:

    .. code-block:: python

        class DomainModel(SDKJsonlMixin):
            ...

        async def get_chunk(ids: list[UUID4], other_arg: str) -> list[DomainModel]:
            return repository.get_domain_models(ids, other_arg)

        file_stream = FileStream(fn=get_chunk, fn_kwargs=[
            {"ids": [id1, id2], "other_arg": "value"},
            {"ids": [id3, id4], "other_arg": "value"}
        ])
        blob_repository.upload_file_to_blob_storage(
            content=file_stream,
            path="path/to/file.jsonl",
            filename="file.jsonl",
        )
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
        if (fn is None) == (generator is None):
            msg = "Either a function or a generator must be provided, but not both."
            raise BlobStorageError(msg)

        self.fn = fn
        self.fn_kwargs = fn_kwargs or []
        self.generator = generator

    async def _to_str(self, data: Streamable) -> str:
        """
        Convert a Streamable object to a string.

        :param data: The Streamable object to convert.
        :type data: Streamable
        :return: The string representation of the Streamable object.
        :rtype: str
        """
        if isinstance(data, list):
            return "".join(await gather(*(self._to_str(item) for item in data)))
        return (
            (await data.to_sdk()).to_jsonl()
            if isinstance(data, SDKJsonlMixin)
            else data
        ) + "\n"

    async def _to_bytes(self, data: Streamable) -> bytes:
        """
        Convert a Streamable object to bytes.

        :param data: The Streamable object to convert.
        :type data: Streamable
        :return: The byte representation of the Streamable object.
        :rtype: bytes
        """
        b = await self._to_str(data)
        return b.encode("utf-8")

    async def stream(self) -> AsyncGenerator[bytes, None]:
        """
        Stream data from the FileStream's function or generator.

        :return: An async generator yielding bytes.
        :rtype: AsyncGenerator[bytes, None]
        :yield: The next chunk of data.
        :rtype: Iterator[AsyncGenerator[bytes, None]]
        """
        if self.generator:
            async for chunk in self.generator:
                yield await self._to_bytes(chunk)
        elif self.fn:
            for kwargs in self.fn_kwargs:
                data = await self.fn(**kwargs)
                yield await self._to_bytes(data)

    async def read(self) -> BytesIO:
        """
        Read all data from the FileStream into memory and return as a file-like object.

        For implementations where async generators are not supported we read all data
        into memory and return a BytesIO object. Currently this applies only to MinIO
        which is only used for local and testing purposes. If this becomes a problem
        we can also look into composing blobs: https://min.io/docs/minio/linux/developers/python/API.html#compose_object

        :return: A BytesIO object containing all the data.
        :rtype: BytesIO
        """
        buffer = BytesIO()
        if self.generator:
            async for chunk in self.generator:
                buffer.write(await self._to_bytes(chunk))
        elif self.fn:
            data = await gather(*[self.fn(**kwargs) for kwargs in self.fn_kwargs])
            for chunk in data:
                buffer.write(await self._to_bytes(chunk))
        buffer.seek(0)
        return buffer
