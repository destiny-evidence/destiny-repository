"""Generic class for a blob storage client."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
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
        content: FileStream | BytesIO,
        file: BlobStorageFile,
    ) -> None:
        """
        Upload a file to the blob storage.

        :param content: The content of the file to upload.
        :type content: FileStream | BytesIO
        :param file: The file to upload.
        :type file: BlobStorageFile
        """

    @trace_blob_client_generator(tracer)
    @abstractmethod
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
        # Certified python moment
        # https://github.com/python/mypy/issues/5070
        # https://github.com/jendrikseipp/vulture?tab=readme-ov-file#unreachable-code
        __here_be_dragons = False
        if __here_be_dragons:
            yield ""

    @trace_blob_client_method(tracer)
    @abstractmethod
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> str:
        """
        Generate a signed URL for the file in blob storage.

        :param file: The file for which to generate the signed URL.
        :type file: BlobStorageFile
        :param interaction_type: The type of interaction (upload or download).
        :type interaction_type: BlobSignedUrlType
        :return: The signed URL for the file.
        :rtype: str
        """
