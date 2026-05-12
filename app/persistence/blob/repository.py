"""Service for managing files in blob storage."""

import hashlib
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from io import BytesIO

from cachetools import LRUCache
from pydantic import HttpUrl

from app.core.config import get_settings
from app.core.exceptions import (
    AzureBlobStorageError,
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


type URLSigner = Callable[[BlobStorageFile, BlobSignedUrlType], Awaitable[HttpUrl]]


class BlobRepository:
    """Repository for managing files in blob storage."""

    def __init__(self) -> None:
        """Initialize the BlobRepository."""
        self._config_cache: LRUCache[BlobStorageFile, GenericBlobStorageClient] = (
            LRUCache(maxsize=1000)
        )
        self._remote_client: RemoteBlobStorageClient | None = None

    async def _preload_config(
        self,
        file: BlobStorageFile,
    ) -> GenericBlobStorageClient:
        """
        Pre-check configuration for blob storage clients.

        :param file: The file to check configuration for.
        :type file: BlobStorageFile
        :raises AzureBlobStorageError: Raised if file location is Azure and
            configuration is missing.
        :raises MinioBlobStorageError: Raised if file location is MinIO and
            configuration is missing.
        :raises BlobStorageError: Raised if file location is unsupported.
        :return: _description_
        :rtype: GenericBlobStorageClient
        """
        # This feels best for now as it avoids unnecessary instantiation, but we
        # can consider just creating the clients if their config is provided in
        # __init__().
        if config := self._config_cache.get(file):
            return config
        if file.location == BlobStorageLocation.AZURE:
            if not settings.azure_blob_config:
                msg = "Azure Blob Storage configuration is not given."
                raise AzureBlobStorageError(msg)
            config = AzureBlobStorageClient(
                settings.azure_blob_config, settings.presigned_url_expiry_seconds
            )
        elif file.location == BlobStorageLocation.MINIO:
            if not settings.minio_config:
                msg = "MinIO configuration is not given."
                raise MinioBlobStorageError(msg)
            config = MinioBlobStorageClient(
                settings.minio_config, settings.presigned_url_expiry_seconds
            )
        elif file.is_remote:
            if self._remote_client is None:
                self._remote_client = RemoteBlobStorageClient()
            config = self._remote_client
        else:
            msg = "Unsupported blob storage location."
            raise BlobStorageError(msg)
        self._config_cache[file] = config
        return config

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
        backend = settings.active_blob_backend
        return BlobStorageFile(
            location=backend.location,
            container=backend.containers[container],
            path=path,
            filename=filename,
        )

    async def upload_file_to_blob_storage(
        self,
        content: FileStream | BytesIO,
        path: str,
        filename: str,
        container: BlobContainer = BlobContainer.OPERATIONS,
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
        :return: The information of the uploaded file.
        :rtype: BlobStorageFile
        """
        file = self.destination(path=path, filename=filename, container=container)
        client = await self._preload_config(file)
        await client.upload_file(content, file)
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
    ) -> HttpUrl:
        """
        Generate a signed URL for a file in Blob Storage.

        :param file: The file for which to generate the signed URL.
        :type file: BlobStorageFile
        :param interaction_type: The type of interaction (upload or download).
        :type interaction_type: BlobSignedUrlType
        :return: The signed URL for the file.
        :rtype: HttpUrl
        """
        client = await self._preload_config(file)
        return HttpUrl(await client.generate_signed_url(file, interaction_type))

    async def copy(
        self, source: BlobStorageFile, destination: BlobStorageFile
    ) -> BlobCopyResult:
        """
        Stream a file from source to destination, computing sha256 and size.

        :param source: The source file to copy.
        :type source: BlobStorageFile
        :param destination: The destination to copy the file to.
        :type destination: BlobStorageFile
        """
        src_client = await self._preload_config(source)
        dest_client = await self._preload_config(destination)

        hasher = hashlib.sha256()
        size = 0

        async def hashed_chunks() -> AsyncIterator[bytes]:
            nonlocal size
            async for chunk in src_client.stream_chunks(source):
                hasher.update(chunk)
                size += len(chunk)
                yield chunk

        await dest_client.upload_file(hashed_chunks(), destination)

        return BlobCopyResult(
            source=source,
            destination=destination,
            byte_size=size,
            sha256_checksum=hasher.hexdigest(),
        )
