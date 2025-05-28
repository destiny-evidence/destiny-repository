"""Minio implementations for blob storage operations."""

import datetime
from collections.abc import AsyncGenerator
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import MinioConfig
from app.core.exceptions import MinioBlobStorageError
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
)
from app.persistence.blob.stream import FileStream


class MinioBlobStorageClient(GenericBlobStorageClient):
    """
    Minio implementation of GenericBlobStorageClient for managing files in Minio.

    Handles authentication and provides methods for upload, streaming,
    and signed URL generation.
    """

    def __init__(self, config: MinioConfig, presigned_url_expiry_seconds: int) -> None:
        """
        Initialize MinioBlobStorageClient with authentication and client setup.

        Raises MinioBlobStorageError if configuration is missing.
        """
        self.host = config.host
        self.access_key = config.access_key
        self.secret_key = config.secret_key
        self.presigned_url_expiry_seconds = presigned_url_expiry_seconds
        self.client = Minio(
            self.host,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=False,
        )

    async def upload_file(
        self,
        content: FileStream | BytesIO,
        file: BlobStorageFile,
    ) -> None:
        """Upload a file to MinIO."""
        try:
            if isinstance(content, FileStream):
                content = await content.read()
            self.client.put_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
                data=content,
                length=content.getbuffer().nbytes,
                content_type=file.content_type,
            )
        except S3Error as e:
            msg = f"Failed to upload file to MinIO: {e}"
            raise MinioBlobStorageError(msg) from e

    async def stream_file(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[str, None]:
        """
        Yield lines from a file in MinIO as a generator.

        Splits the file content by newline.
        """
        try:
            response = self.client.get_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
            )
            buffer = ""
            for chunk in response.stream(1024):
                text = chunk.decode("utf-8")
                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            if buffer:
                yield buffer
        except S3Error as e:
            msg = f"Failed to get file from MinIO: {e}"
            raise MinioBlobStorageError(msg) from e

    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> str:
        """Get a signed URL for a file in MinIO."""
        try:
            if interaction_type == BlobSignedUrlType.DOWNLOAD:
                return self.client.presigned_get_object(
                    bucket_name=file.container,
                    object_name=f"{file.path}/{file.filename}",
                    expires=datetime.timedelta(
                        seconds=self.presigned_url_expiry_seconds
                    ),
                )
            if interaction_type == BlobSignedUrlType.UPLOAD:
                return self.client.presigned_put_object(
                    bucket_name=file.container,
                    object_name=f"{file.path}/{file.filename}",
                    expires=datetime.timedelta(
                        seconds=self.presigned_url_expiry_seconds
                    ),
                )
            msg = f"Interaction type {interaction_type} is not supported."
            raise NotImplementedError(msg)
        except S3Error as e:
            msg = f"Failed to get signed URL from MinIO: {e}"
            raise MinioBlobStorageError(msg) from e
