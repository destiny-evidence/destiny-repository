"""Service for managing files in blob storage."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO

from cachetools.func import lru_cache
from pydantic import HttpUrl

from app.core.config import get_settings
from app.core.exceptions import (
    AzureBlobStorageError,
    BlobStorageError,
    MinioBlobStorageError,
)
from app.core.logger import get_logger
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.clients.azure import AzureBlobStorageClient
from app.persistence.blob.clients.minio import MinioBlobStorageClient
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
)
from app.persistence.blob.stream import FileStream

settings = get_settings()
logger = get_logger()


@lru_cache()
async def _preload_config(
    file: BlobStorageFile,
) -> GenericBlobStorageClient:
    """Pre-check configuration for blob storage clients."""
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
    msg = "Unsupported blob storage location."
    raise BlobStorageError(msg)


async def upload_file_to_blob_storage(
    content: FileStream | BytesIO,
    path: str,
    filename: str,
) -> BlobStorageFile:
    """Upload a file to Blob Storage."""
    file = BlobStorageFile(
        location=settings.default_blob_location,
        container=settings.default_blob_container,
        path=path,
        filename=filename,
    )
    client = await _preload_config(file)
    await client.upload_file(content, file)
    return file


@asynccontextmanager
async def stream_file_from_blob_storage(
    file: BlobStorageFile,
) -> AsyncGenerator[AsyncIterator[str], None]:
    """Async context manager to get lines from a file in Blob Storage."""
    client = await _preload_config(file)
    yield client.stream_file(file)


async def get_signed_url(
    file: BlobStorageFile,
    interaction_type: BlobSignedUrlType,
) -> HttpUrl:
    """Get a signed URL for a file in Blob Storage."""
    client = await _preload_config(file)
    return HttpUrl(await client.generate_signed_url(file, interaction_type))
