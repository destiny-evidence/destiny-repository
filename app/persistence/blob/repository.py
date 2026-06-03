"""Service for managing files in blob storage."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import cached_property
from io import BytesIO
from typing import Protocol

from pydantic import HttpUrl

from app.core.config import (
    AzureBlobConfig,
    Environment,
    MinioConfig,
    get_settings,
)
from app.core.exceptions import (
    AzureBlobStorageError,
    BlobSizeExceededError,
    BlobStorageError,
    MinioBlobStorageError,
)
from app.core.telemetry.logger import get_logger
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.clients.azure import AzureBlobStorageClient
from app.persistence.blob.clients.minio import MinioBlobStorageClient
from app.persistence.blob.clients.remote import RemoteBlobStorageClient
from app.persistence.blob.models import (
    BlobContainer,
    BlobCopyResult,
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
)
from app.persistence.blob.stream import FileStream

settings = get_settings()
logger = get_logger(__name__)


class URLSigner(Protocol):
    """Callable signature for signing a blob storage file into a URL."""

    async def __call__(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
        content_disposition: str | None = "attachment",
    ) -> HttpUrl:
        """Sign ``file`` for ``interaction_type``, returning a presigned URL."""
        ...


class _BlobClientRegistry:
    """
    Process-wide owner of concrete blob backend clients.

    This defers instantiation and teardown of backend clients to the application
    lifecycle, rather than per-repository or per-request.
    """

    def __init__(self) -> None:
        self._clients: dict[BlobStorageLocation, GenericBlobStorageClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, file: BlobStorageFile) -> GenericBlobStorageClient:
        if client := self._clients.get(file.location):
            return client
        async with self._lock:
            if client := self._clients.get(file.location):
                return client
            client = self._instantiate(file)
            self._clients[file.location] = client
            return client

    @staticmethod
    def _instantiate(file: BlobStorageFile) -> GenericBlobStorageClient:
        if file.location == BlobStorageLocation.AZURE:
            if not settings.azure_blob_config:
                msg = "Azure Blob Storage configuration is not given."
                raise AzureBlobStorageError(msg)
            return AzureBlobStorageClient(
                settings.azure_blob_config, settings.presigned_url_expiry_seconds
            )
        if file.location == BlobStorageLocation.MINIO:
            if not settings.minio_config:
                msg = "MinIO configuration is not given."
                raise MinioBlobStorageError(msg)
            return MinioBlobStorageClient(
                settings.minio_config, settings.presigned_url_expiry_seconds
            )
        if file.is_remote:
            return RemoteBlobStorageClient()
        msg = "Unsupported blob storage location."
        raise BlobStorageError(msg)

    async def aclose(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            results = await asyncio.gather(
                *(c.aclose() for c in clients), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("Error closing blob client", exc_info=result)


_registry = _BlobClientRegistry()


async def close_blob_clients() -> None:
    """Release every backend client held by the process-wide registry."""
    await _registry.aclose()


class BlobRepository:
    """Repository for managing files in blob storage."""

    @cached_property
    def _write_backend(self) -> AzureBlobConfig | MinioConfig:
        """The blob backend that new files will be written to."""
        if settings.running_locally:
            if settings.minio_config:
                return settings.minio_config
            if settings.azure_blob_config:
                return settings.azure_blob_config
            if settings.env == Environment.TEST:
                # No blob config in tests; assume mocked.
                return MinioConfig(
                    host="test",
                    access_key="test",
                    secret_key="test",  # noqa: S106
                    containers={c: "test" for c in BlobContainer},
                )
        if not settings.azure_blob_config:
            msg = "Azure Blob Storage configuration is not given."
            raise ValueError(msg)
        return settings.azure_blob_config

    async def _preload_config(
        self,
        file: BlobStorageFile,
    ) -> GenericBlobStorageClient:
        """Return the shared backend client for ``file``'s location."""
        return await _registry.get(file)

    def destination(
        self,
        path: str,
        filename: str,
        container: BlobContainer = BlobContainer.OPERATIONS,
    ) -> BlobStorageFile:
        """
        Reserve a BlobStorageFile destination without performing any I/O.

        Useful for pre-allocating a location that will be written to later
        (e.g. a record stored before its content is uploaded).
        """
        return BlobStorageFile(
            location=self._write_backend.location,
            container=self._write_backend.containers[container],
            path=path,
            filename=filename,
        )

    async def upload_file_to_blob_storage(
        self,
        content: FileStream | BytesIO,
        path: str,
        filename: str,
        container: BlobContainer = BlobContainer.OPERATIONS,
        content_type: str | None = None,
    ) -> BlobStorageFile:
        """
        Upload a file to Blob Storage.

        See :class:`app.persistence.blob.stream.FileStream` for
        examples of how to create and use a ``FileStream`` object.

        :param content: The content of the file to upload.
        :type content: FileStream | BytesIO
        :param path: The path to upload the file to.
        :type path: str
        :param filename: The name of the file to upload.
        :type filename: str
        :param container: The logical container to upload the file to. The
            physical container name is resolved via the active blob backend.
        :type container: BlobContainer
        :param content_type: Optional MIME type to attach to the uploaded
            object. If not provided, it is inferred from ``filename``.
        :type content_type: str | None
        :return: The information of the uploaded file.
        :rtype: BlobStorageFile
        """
        file = self.destination(path=path, filename=filename, container=container)
        client = await self._preload_config(file)
        await client.upload_file(content, file, content_type=content_type)
        return file

    @asynccontextmanager
    async def stream_file_from_blob_storage(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[AsyncIterator[str], None]:
        """
        Stream a file line-by-line from Blob Storage.

        Usage:

        .. code-block:: python

            async with blob_repo.stream_file_from_blob_storage(file) as stream:
                async for line in stream:
                    print(line)

        :param file: The file to stream.
        :type file: BlobStorageFile
        :return: An async generator that yields lines one at a time from the file.
        :rtype: AsyncGenerator[str, None]
        :yield: Lines from the file, one at a time.
        :rtype: Iterator[AsyncGenerator[AsyncIterator[str], None]]
        """
        client = await self._preload_config(file)
        yield client.stream_file(file)

    async def get_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
        content_disposition: str | None = "attachment",
    ) -> HttpUrl:
        """
        Generate a signed URL for a file in Blob Storage.

        :param file: The file for which to generate the signed URL.
        :type file: BlobStorageFile
        :param interaction_type: The type of interaction (upload or download).
        :type interaction_type: BlobSignedUrlType
        :param content_disposition: Override for the signed download's
            Content-Disposition response header. Defaults to ``"attachment"``
            so browsers never render fetched bytes inline.
            Pass ``None`` to opt out if a future caller wants inline rendering.
        :type content_disposition: str | None
        :return: The signed URL for the file.
        :rtype: HttpUrl
        """
        client = await self._preload_config(file)
        return HttpUrl(
            await client.generate_signed_url(
                file, interaction_type, content_disposition
            )
        )

    async def copy(
        self,
        source: BlobStorageFile,
        destination: BlobStorageFile,
        max_bytes: int | None = None,
        content_type: str | None = None,
    ) -> BlobCopyResult:
        """
        Stream a file from source to destination, computing sha256 and size.

        :param source: The source file to copy.
        :type source: BlobStorageFile
        :param destination: The destination to copy the file to.
        :type destination: BlobStorageFile
        :param max_bytes: Optional cap on the total bytes streamed. The stream
            is aborted (raising :class:`BlobSizeExceededError`) once the
            cumulative chunk size strictly exceeds this. ``None`` disables the
            check.
        :type max_bytes: int | None
        :param content_type: MIME type to attach to the uploaded destination.
            If the caller has an authoritative content type (e.g. declared on
            a full-text enhancement), pass it here so it isn't lossily
            re-derived from the destination filename. Defaults to ``None``,
            which lets the backend infer from ``destination.filename``.
        :type content_type: str | None
        :raises BlobSizeExceededError: if ``max_bytes`` is set and the source
            yields more bytes than allowed.
        """
        if destination.location != self._write_backend.location:
            msg = (
                f"Destination location {destination.location} does not match the "
                f"active write backend {self._write_backend.location}."
            )
            raise BlobStorageError(msg)

        src_client = await self._preload_config(source)
        dest_client = await self._preload_config(destination)

        hasher = hashlib.sha256()
        size = 0

        async def hashed_chunks() -> AsyncIterator[bytes]:
            nonlocal size
            async for chunk in src_client.stream_chunks(source):
                hasher.update(chunk)
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    msg = (
                        f"Source {source.to_uri()} exceeds max_bytes={max_bytes} "
                        f"(streamed at least {size} bytes before abort)."
                    )
                    raise BlobSizeExceededError(msg)
                yield chunk

        await dest_client.upload_file(
            hashed_chunks(), destination, content_type=content_type
        )

        return BlobCopyResult(
            source=source,
            destination=destination,
            byte_size=size,
            sha256_checksum=hasher.hexdigest(),
        )
