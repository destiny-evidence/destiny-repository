"""File handling utilities for Azure Blob Storage."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field


class AzureBlobSignedUrlType(StrEnum):
    """Azure Blob Storage interaction types."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class AzureBlobStorageFile(BaseModel):
    """Model to represent Azure Blob Storage files."""

    container: str = Field(
        default="TODO",
        description="The name of the container in Azure Blob Storage.",
    )
    path: str = Field(
        description="The path to the file in Azure Blob Storage.",
    )
    filename: str = Field(
        description="The name of the file in Azure Blob Storage.",
    )

    def to_signed_url(self, _interaction_type: AzureBlobSignedUrlType) -> str:
        """Return a freshly generated signed URL."""
        return "TODO"

    def to_sql(self) -> str:
        """Return the SQL persistence representation of the file."""
        return f"{self.container}/{self.path}/{self.filename}"

    @classmethod
    def from_sql(cls, sql: str) -> Self:
        """Populate the model from a SQL representation."""
        parts = sql.split("/")
        if len(parts) < 3:  # noqa: PLR2004
            msg = "Invalid SQL representation"
            raise ValueError(msg)
        return cls(
            container=parts[0],
            path="/".join(parts[1:-1]),
            filename=parts[-1],
        )


async def upload_file_to_azure_blob_storage(
    file: bytes,
    path: str,
    filename: str,
) -> AzureBlobStorageFile:
    """Upload a file to Azure Blob Storage."""
    return AzureBlobStorageFile(
        path=path,
        filename=filename,
    )
