"""Azure implementation for Blob Storage operations."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, AsyncIterator
from io import BytesIO

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    ContentSettings,
    UserDelegationKey,
    generate_blob_sas,
)
from azure.storage.blob.aio import BlobServiceClient
from cachetools import TTLCache
from opentelemetry import trace

from app.core.config import AzureBlobConfig
from app.core.exceptions import AzureBlobStorageError
from app.core.telemetry.blob import (
    trace_blob_client_generator,
    trace_blob_client_method,
)
from app.core.telemetry.logger import get_logger
from app.persistence.blob.client import GenericBlobStorageClient
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
    infer_content_type,
)
from app.persistence.blob.stream import FileStream

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


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
        self.account_name = config.storage_account_name
        self.credential = config.credential
        self.presigned_url_expiry_seconds = presigned_url_expiry_seconds
        self.uses_managed_identity = config.uses_managed_identity
        self.user_delegation_key_duration = config.user_delegation_key_duration
        # Hold the aio credential explicitly so aclose() can release it; the
        # azure SDK's close() doesn't propagate to externally-constructed
        # credentials, so without this its httpx clients leak.
        self._aio_credential = (
            DefaultAzureCredential() if self.uses_managed_identity else None
        )
        self.blob_service_client = BlobServiceClient(
            self.account_url,
            credential=self._aio_credential
            if self._aio_credential is not None
            else self.credential,
        )
        self._user_delegation_key_cache: TTLCache[None, UserDelegationKey] = TTLCache(
            maxsize=1, ttl=self.user_delegation_key_duration / 2
        )
        self._user_delegation_key_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close the aiohttp-backed BlobServiceClient and aio credential."""
        await self.blob_service_client.close()
        if self._aio_credential is not None:
            await self._aio_credential.close()

    @trace_blob_client_method(tracer)
    async def upload_file(
        self,
        content: FileStream | BytesIO | AsyncIterator[bytes],
        file: BlobStorageFile,
        content_type: str | None = None,
    ) -> None:
        """Upload a file to Azure Blob Storage using async streaming."""
        blob_client = self.blob_service_client.get_blob_client(
            container=file.container, blob=f"{file.path}/{file.filename}"
        )
        content_settings = ContentSettings(
            content_type=content_type or infer_content_type(file.filename)
        )
        try:
            await blob_client.upload_blob(
                content.stream() if isinstance(content, FileStream) else content,
                overwrite=True,
                content_settings=content_settings,
            )
        except Exception as e:
            msg = f"Failed to upload file to Azure Blob Storage: {e}"
            raise AzureBlobStorageError(msg) from e

    @trace_blob_client_generator(tracer)
    async def stream_chunks(
        self,
        file: BlobStorageFile,
    ) -> AsyncGenerator[bytes, None]:
        """Yield raw byte chunks from a file in Azure Blob Storage."""
        blob_client = self.blob_service_client.get_blob_client(
            container=file.container, blob=f"{file.path}/{file.filename}"
        )
        try:
            stream = await blob_client.download_blob()
            async for chunk in stream.chunks():
                yield chunk
        except Exception as e:
            msg = f"Failed to stream file from Azure Blob Storage: {e}"
            raise AzureBlobStorageError(msg) from e

    async def _get_user_delegation_key(self) -> UserDelegationKey:
        """Get a user delegation key from managed identity, cached."""
        if cached := self._user_delegation_key_cache.get(None):
            return cached
        async with self._user_delegation_key_lock:
            # Re-check under the lock so concurrent callers single-flight the fetch.
            if cached := self._user_delegation_key_cache.get(None):
                return cached
            user_delegation_key = (
                await self.blob_service_client.get_user_delegation_key(
                    datetime.datetime.now(datetime.UTC),
                    datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(seconds=self.user_delegation_key_duration),
                )
            )
            if not user_delegation_key.value:
                msg = "Failed to get user delegation key from Azure Blob Storage."
                raise AzureBlobStorageError(msg)
            self._user_delegation_key_cache[None] = user_delegation_key
            return user_delegation_key

    @trace_blob_client_method(tracer)
    async def generate_signed_url(
        self,
        file: BlobStorageFile,
        interaction_type: BlobSignedUrlType,
        content_disposition: str | None,
    ) -> str:
        """Get a signed URL for a file in Azure Blob Storage."""
        try:
            blob_name = f"{file.path}/{file.filename}"

            permission = (
                BlobSasPermissions(read=True)
                if interaction_type == BlobSignedUrlType.DOWNLOAD
                else BlobSasPermissions(write=True)
            )
            sas_content_disposition = (
                content_disposition
                if interaction_type == BlobSignedUrlType.DOWNLOAD
                else None
            )
            sas_token = generate_blob_sas(
                account_name=self.account_name,
                container_name=file.container,
                blob_name=blob_name,
                account_key=self.credential if not self.uses_managed_identity else None,
                user_delegation_key=await self._get_user_delegation_key()
                if self.uses_managed_identity
                else None,
                permission=permission,
                expiry=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=self.presigned_url_expiry_seconds),
                content_disposition=sas_content_disposition,
            )
        except Exception as e:
            msg = f"Failed to generate signed URL for Azure Blob Storage: {e}"
            raise AzureBlobStorageError(msg) from e
        else:
            return f"{self.account_url}/{file.container}/{blob_name}?{sas_token}"
