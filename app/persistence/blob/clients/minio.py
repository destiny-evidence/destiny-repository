"""Minio implementations for blob storage operations."""

import datetime
from collections.abc import AsyncGenerator, AsyncIterator
from io import BytesIO

from minio import Minio
from minio.error import S3Error
from opentelemetry import trace

from app.core.config import MinioConfig
from app.core.exceptions import MinioBlobStorageError
from app.core.telemetry.blob import (
    trace_blob_client_generator,
    trace_blob_client_method,
)
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
)
from app.persistence.blob.stream import FileStream

tracer = trace.get_tracer(__name__)


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

    @trace_blob_client_method(tracer)
    async def upload_file(
        self,
        content: FileStream | BytesIO | AsyncIterator[bytes],
        file: BlobStorageFile,
    ) -> None:
        """Upload a file to MinIO."""
        try:
            if isinstance(content, FileStream):
                buffer = await content.read()
            elif isinstance(content, BytesIO):
                buffer = content
            else:
                # Async iterator of bytes: buffer in memory. MinIO is dev/test only,
                # so memory pressure is acceptable.
                buffer = BytesIO()
                async for chunk in content:
                    buffer.write(chunk)
                buffer.seek(0)
            self.client.put_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
                data=buffer,
                length=buffer.getbuffer().nbytes,
                content_type=file.content_type or "application/octet-stream",
            )
        except S3Error as e:
            msg = f"Failed to upload file to MinIO: {e}"
            raise MinioBlobStorageError(msg) from e

    @trace_blob_client_generator(tracer)
    async def stream_chunks(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[bytes, None]:
        """Yield raw byte chunks from a file in MinIO."""
        try:
            response = self.client.get_object(
                bucket_name=file.container,
                object_name=f"{file.path}/{file.filename}",
            )
            for chunk in response.stream(1024):
                yield chunk
        except S3Error as e:
            msg = f"Failed to get file from MinIO: {e}"
            raise MinioBlobStorageError(msg) from e

    @trace_blob_client_method(tracer)
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> str:
        """Get a signed URL for a file in MinIO."""
        try:
            if interaction_type == BlobSignedUrlType.DOWNLOAD:
                url = self.client.presigned_get_object(
                    bucket_name=file.container,
                    object_name=f"{file.path}/{file.filename}",
                    expires=datetime.timedelta(
                        seconds=self.presigned_url_expiry_seconds
                    ),
                )
            if interaction_type == BlobSignedUrlType.UPLOAD:
                url = self.client.presigned_put_object(
                    bucket_name=file.container,
                    object_name=f"{file.path}/{file.filename}",
                    expires=datetime.timedelta(
                        seconds=self.presigned_url_expiry_seconds
                    ),
                )
        except S3Error as e:
            msg = f"Failed to get signed URL from MinIO: {e}"
            raise MinioBlobStorageError(msg) from e
        else:
            if not url:
                msg = "Failed to generate signed URL from MinIO."
                raise MinioBlobStorageError(msg)
            return url
