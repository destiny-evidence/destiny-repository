"""Implementations for remote blob storage operations."""

from collections.abc import AsyncGenerator, AsyncIterator
from io import BytesIO

import httpx
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.core.exceptions import RemoteBlobStorageError
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


class RemoteBlobStorageClient(GenericBlobStorageClient):
    """Read-only client for fetching files from remote (http) URLs."""

    def __init__(self) -> None:
        """Initialize RemoteBlobStorageClient."""
        self._client = httpx.AsyncClient(follow_redirects=False)
        HTTPXClientInstrumentor().instrument_client(self._client)

    @trace_blob_client_method(tracer)
    async def upload_file(
        self,
        content: FileStream | BytesIO | AsyncIterator[bytes],
        file: BlobStorageFile,
        content_type: str | None = None,
    ) -> None:
        """
        Raise, uploads to remote URLs are not supported.

        (They could be in the future if we wanted to support PUTs to arbitrary URLs).
        """
        del content, file, content_type
        msg = "Upload is not supported for RemoteBlobStorageClient."
        raise RemoteBlobStorageError(msg)

    @trace_blob_client_generator(tracer)
    async def stream_chunks(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[bytes, None]:
        """Yield raw byte chunks streamed from a remote URL."""
        try:
            async with self._client.stream("GET", file.to_uri()) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.HTTPError as e:
            msg = f"Failed to stream file from remote URL {file.to_uri()}: {e}"
            raise RemoteBlobStorageError(msg) from e

    @trace_blob_client_method(tracer)
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
        content_disposition: str | None,
    ) -> str:
        """Raise, remote URLs are themselves already URLs."""
        del file, interaction_type, content_disposition
        msg = "Signed URL generation is not supported for RemoteBlobStorageClient."
        raise RemoteBlobStorageError(msg)

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
