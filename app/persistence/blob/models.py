"""Models for handling files in blob storage."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field

from app.core.exceptions import BlobStorageError


class BlobSignedUrlType(StrEnum):
    """Blob Storage interaction types."""

    DOWNLOAD = "download"
    UPLOAD = "upload"


class BlobStorageLocation(StrEnum):
    """Blob Storage locations."""

    AZURE = "azure"
    MINIO = "minio"


class BlobStorageFile(BaseModel):
    """Model to represent Blob Storage files."""

    location: BlobStorageLocation = Field(
        default=BlobStorageLocation.AZURE,
        description="The location of the blob storage.",
    )
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

    def to_signed_url(self, _interaction_type: BlobSignedUrlType) -> str:
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
            msg = f"Invalid SQL representation {sql} for BlobStorageFile."
            raise BlobStorageError(msg)
        return cls(
            container=parts[0],
            path="/".join(parts[1:-1]),
            filename=parts[-1],
        )
