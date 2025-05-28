"""Generic class for a blob storage client."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from io import BytesIO

from app.core.config import get_settings
from app.persistence.blob.models import BlobSignedUrlType, BlobStorageFile
from app.persistence.blob.stream import FileStream

settings = get_settings()


class GenericBlobStorageClient(ABC):
    """
    Abstract base class for blob storage clients.

    This class defines the interface for blob storage operations.
    """

    @abstractmethod
    async def upload_file(
        self,
        content: FileStream | BytesIO,
        file: BlobStorageFile,
    ) -> None:
        """Upload a file to the blob storage."""

    @abstractmethod
    async def stream_file(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[str, None]:
        """Stream a file from the blob storage."""
        # Certified python moment
        # https://github.com/python/mypy/issues/5070
        if False:
            yield

    @abstractmethod
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> str:
        """Generate a signed URL for accessing a file in the blob storage."""
