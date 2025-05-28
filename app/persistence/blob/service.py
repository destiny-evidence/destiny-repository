"""
Service for managing files in blob storage.

TODO: implement streaming on gets and puts instead of in-memory.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO

from pydantic import HttpUrl

from app.core.config import get_settings
from app.core.exceptions import BlobStorageError, MinioBlobStorageError
from app.core.logger import get_logger
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
)
from app.persistence.blob.stream import FileStream

settings = get_settings()
logger = get_logger()

if settings.minio_config:
    from minio import Minio
    from minio.error import S3Error


async def upload_file_to_minio(
    content: FileStream | BytesIO,
    file: BlobStorageFile,
) -> None:
    """Upload a file to MinIO."""
    if not settings.minio_config:
        msg = "MinIO configuration is not set."
        raise MinioBlobStorageError(msg)

    minio_client = Minio(
        settings.minio_config.host,
        access_key=settings.minio_config.access_key,
        secret_key=settings.minio_config.secret_key,
        secure=False,
    )
    try:
        if isinstance(content, FileStream):
            content = await content.read()
        minio_client.put_object(
            bucket_name=file.container,
            object_name=f"{file.path}/{file.filename}",
            data=content,
            length=content.getbuffer().nbytes,
            content_type=file.content_type,
        )
    except S3Error as e:
        msg = f"Failed to upload file to MinIO: {e}"
        raise BlobStorageError(msg) from e


async def stream_file_from_minio(
    file: BlobStorageFile,
) -> AsyncGenerator[str, None]:
    """
    Yield lines from a file in MinIO as a generator, split by newline.

    This mimics httpx's aiter_lines() functionality.
    """
    if not settings.minio_config:
        msg = "MinIO configuration is not set."
        raise MinioBlobStorageError(msg)

    minio_client = Minio(
        settings.minio_config.host,
        access_key=settings.minio_config.access_key,
        secret_key=settings.minio_config.secret_key,
        secure=False,
    )
    try:
        response = minio_client.get_object(
            bucket_name=file.container,
            object_name=f"{file.path}/{file.filename}",
        )
        buffer = ""
        # Iterate over the response stream in chunks
        for chunk in response.stream(1024):  # 1KB chunks
            text = chunk.decode("utf-8")
            buffer += text
            # Split the buffer by newline and yield each line
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        # If there's any remaining text in the buffer, yield it as the last line
        if buffer:
            yield buffer
    except S3Error as e:
        msg = f"Failed to get file from MinIO: {e}"
        raise BlobStorageError(msg) from e


def get_signed_url_from_minio(
    file: BlobStorageFile,
    interaction_type: BlobSignedUrlType,
) -> str:
    """Get a signed URL for a file in MinIO."""
    if not settings.minio_config:
        msg = "MinIO configuration is not set."
        raise MinioBlobStorageError(msg)

    minio_client = Minio(
        settings.minio_config.host,
        access_key=settings.minio_config.access_key,
        secret_key=settings.minio_config.secret_key,
        secure=False,
    )
    try:
        if interaction_type == BlobSignedUrlType.DOWNLOAD:
            return minio_client.presigned_get_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
            )
        if interaction_type == BlobSignedUrlType.UPLOAD:
            return minio_client.presigned_put_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
            )
        msg = f"Interaction type {interaction_type} is not supported."
        raise NotImplementedError(msg)
    except S3Error as e:
        msg = f"Failed to get signed URL from MinIO: {e}"
        raise BlobStorageError(msg) from e


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

    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        await upload_file_to_minio(content, file)

    return file


@asynccontextmanager
async def stream_file_from_blob_storage(
    file: BlobStorageFile,
) -> AsyncGenerator[AsyncIterator[str], None]:
    """Async context manager to get lines from a file in Blob Storage."""
    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        yield stream_file_from_minio(file)
        return
    raise NotImplementedError


def get_signed_url(
    file: BlobStorageFile | None,
    interaction_type: BlobSignedUrlType,
) -> HttpUrl | None:
    """
    Get a signed URL for a file in Blob Storage.

    Generally called in a synchronous context (eg translating models),
    so we don't use async here.
    """
    if not file:
        return None
    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        url = get_signed_url_from_minio(file, interaction_type)
        return HttpUrl(url)
    raise NotImplementedError
