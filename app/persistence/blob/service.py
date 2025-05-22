"""
Service for managing files in blob storage.

TODO: implement streaming on gets and puts instead of in-memory.
"""

from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings
from app.core.exceptions import BlobStorageError, MinioBlobStorageError
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
    BlobStorageLocation,
)

settings = get_settings()


async def upload_file_to_minio(
    content: BytesIO,
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
        minio_client.put_object(
            bucket_name=file.container,
            object_name=f"{file.path}/{file.filename}",
            data=content,
            length=-1,
            content_type="application/octet-stream",
        )
    except S3Error as e:
        msg = f"Failed to upload file to MinIO: {e}"
        raise BlobStorageError(msg) from e


async def get_file_from_minio(
    file: BlobStorageFile,
) -> bytes:
    """Get a file from MinIO."""
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
        return response.read()
    except S3Error as e:
        msg = f"Failed to get file from MinIO: {e}"
        raise BlobStorageError(msg) from e


async def get_signed_url_from_minio(
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
    content: BytesIO,
    path: str,
    filename: str,
) -> BlobStorageFile:
    """Upload a file to Blob Storage."""
    file = BlobStorageFile(
        path=path,
        filename=filename,
    )

    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        await upload_file_to_minio(content, file)

    return file


async def get_file_from_blob_storage(
    file: BlobStorageFile,
) -> bytes:
    """Get a file from Blob Storage."""
    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        return await get_file_from_minio(file)

    raise NotImplementedError


async def get_signed_url(
    file: BlobStorageFile,
    interaction_type: BlobSignedUrlType,
) -> str:
    """Get a signed URL for a file in Blob Storage."""
    if file.location == BlobStorageLocation.AZURE:
        raise NotImplementedError
    if file.location == BlobStorageLocation.MINIO:
        return await get_signed_url_from_minio(file, interaction_type)

    raise NotImplementedError
