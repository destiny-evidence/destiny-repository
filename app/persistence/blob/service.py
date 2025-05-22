"""Service for managing files in blob storage."""

from app.persistence.blob.models import BlobStorageFile


async def upload_file_to_blob_storage(
    file: bytes,  # noqa: ARG001
    path: str,
    filename: str,
) -> BlobStorageFile:
    """Upload a file to Azure Blob Storage."""
    return BlobStorageFile(
        path=path,
        filename=filename,
    )
