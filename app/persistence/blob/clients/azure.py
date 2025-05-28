"""Azure implementation for Blob Storage operations."""

import datetime
from collections.abc import AsyncGenerator
from io import BytesIO

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient
from cachetools.func import ttl_cache

from app.core.config import AzureBlobConfig
from app.core.exceptions import AzureBlobStorageError
from app.core.logger import get_logger
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
)
from app.persistence.blob.stream import FileStream

logger = get_logger()
USER_DELEGATION_KEY_DURATION = 60 * 60 * 24


class AzureBlobStorageClient(GenericBlobStorageClient):
    """
    Azure implementation of GenericBlobStorageClient for managing files in Azure.

    Handles authentication and provides methods for upload, streaming,
    and signed URL generation.
    """

    def __init__(
        self, config: AzureBlobConfig, presigned_url_expiry_seconds: int
    ) -> None:
        """
        Initialize AzureBlobStorageClient with authentication and client setup.

        Raises BlobStorageError if configuration is missing.
        """
        self.account_url = config.account_url
        self.container = config.container
        self.credential = config.credential
        self.presigned_url_expiry_seconds = presigned_url_expiry_seconds
        self.uses_managed_identity = config.uses_managed_identity
        self.blob_service_client = BlobServiceClient(
            self.account_url,
            credential=DefaultAzureCredential()
            if self.uses_managed_identity
            else self.credential,
        )

    async def upload_file(
        self,
        content: FileStream | BytesIO,
        file: BlobStorageFile,
    ) -> None:
        """Upload a file to Azure Blob Storage using async streaming."""
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container, blob=f"{file.path}/{file.filename}"
        )
        try:
            if isinstance(content, FileStream):
                await blob_client.upload_blob(content.stream(), overwrite=True)
            else:
                await blob_client.upload_blob(content, overwrite=True)
        except Exception as e:
            msg = f"Failed to upload file to Azure Blob Storage: {e}"
            raise AzureBlobStorageError(msg) from e

    async def stream_file(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[str, None]:
        """
        Yield lines from a file in Azure Blob Storage as a generator.

        Splits the file content by newline.
        """
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container, blob=f"{file.path}/{file.filename}"
        )
        try:
            stream = await blob_client.download_blob()
            buffer = ""
            async for chunk in stream.chunks():
                text = chunk.decode("utf-8")
                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            if buffer:
                yield buffer
        except Exception as e:
            msg = f"Failed to stream file from Azure Blob Storage: {e}"
            raise AzureBlobStorageError(msg) from e

    @ttl_cache(ttl=USER_DELEGATION_KEY_DURATION / 2)
    async def _get_user_delegation_key(self) -> str:
        """Get a user delegation key from managed identity."""
        user_delegation_key = await self.blob_service_client.get_user_delegation_key(
            datetime.datetime.now(datetime.UTC),
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=USER_DELEGATION_KEY_DURATION),
        )
        if not user_delegation_key.value:
            msg = "Failed to get user delegation key from Azure Blob Storage."
            raise AzureBlobStorageError(msg)
        return user_delegation_key.value

    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
    ) -> str:
        """Get a signed URL for a file in Azure Blob Storage."""
        blob_name = f"{file.path}/{file.filename}"

        account_key = (
            await self._get_user_delegation_key()
            if self.uses_managed_identity
            else self.credential
        )
        permission = (
            BlobSasPermissions(read=True)
            if interaction_type == BlobSignedUrlType.DOWNLOAD
            else BlobSasPermissions(write=True)
        )
        sas_token = generate_blob_sas(
            account_name=self.account_url.split("//")[1].split(".")[0],
            container_name=self.container,
            blob_name=blob_name,
            account_key=account_key,
            permission=permission,
            expiry=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=self.presigned_url_expiry_seconds),
        )
        return f"{self.account_url}/{self.container}/{blob_name}?{sas_token}"
