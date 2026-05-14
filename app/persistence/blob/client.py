"""Generic class for a blob storage client."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from io import BytesIO

from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.blob import (
    trace_blob_client_generator,
    trace_blob_client_method,
)
from app.persistence.blob.models import BlobSignedUrlType, BlobStorageFile
from app.persistence.blob.stream import FileStream

settings = get_settings()
tracer = trace.get_tracer(__name__)


class GenericBlobStorageClient(ABC):
    """
    Abstract base class for blob storage clients.

    This class defines the interface for blob storage operations.
    """

    @trace_blob_client_method(tracer)
    @abstractmethod
    async def upload_file(
        self,
        content: FileStream | BytesIO | AsyncIterator[bytes],
        file: BlobStorageFile,
        content_type: str | None = None,
    ) -> None:
        """
        Upload a file to the blob storage.

        :param content: The content of the file to upload.
        :type content: FileStream | BytesIO | AsyncIterator[bytes]
        :param file: The file to upload.
        :type file: BlobStorageFile
        :param content_type: Optional MIME type to attach to the uploaded
            object. If not provided, implementations infer it from
            ``file.filename``.
        :type content_type: str | None
        """

    @trace_blob_client_generator(tracer)
    @abstractmethod
    async def stream_chunks(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream a file as raw byte chunks from the blob storage.

        :param file: The file to stream.
        :type file: BlobStorageFile
        :return: An async generator that yields byte chunks from the file.
        :rtype: AsyncGenerator[bytes, None]
        """
        # https://github.com/python/mypy/issues/5070
        __here_be_dragons = False
        if __here_be_dragons:
            yield b""

    @trace_blob_client_generator(tracer)
    async def stream_file(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[str, None]:
        """
        Stream a file line-by-line from the blob storage.

        :param file: The file to stream.
        :type file: BlobStorageFile
        :return: An async generator that yields lines from the file.
        :rtype: AsyncGenerator[str, None]
        """
        buffer = ""
        async for chunk in self.stream_chunks(file):
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        if buffer:
            yield buffer

    @trace_blob_client_method(tracer)
    @abstractmethod
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
        content_disposition: str | None,
    ) -> str:
        """
        Generate a signed URL for the file in blob storage.

        :param file: The file for which to generate the signed URL.
        :type file: BlobStorageFile
        :param interaction_type: The type of interaction (upload or download).
        :type interaction_type: BlobSignedUrlType
        :param content_disposition: Override for the Content-Disposition response
            header served when the signed URL is fetched. Set to ``"attachment"``
            for untrusted content (e.g. full-text blobs) to neutralize inline
            browser rendering. Ignored for ``UPLOAD``.
        :type content_disposition: str | None
        :return: The signed URL for the file.
        :rtype: str
        """
