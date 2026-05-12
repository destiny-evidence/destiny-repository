"""Models for handling files in blob storage."""

from enum import StrEnum, auto
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

from app.core.exceptions import BlobStorageError
from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)


class BlobSignedUrlType(StrEnum):
    """Blob Storage interaction types."""

    DOWNLOAD = auto()
    UPLOAD = auto()


class BlobStorageLocation(StrEnum):
    """Blob Storage locations."""

    AZURE = auto()
    MINIO = auto()
    REMOTE = auto()


class BlobContainer(StrEnum):
    """Blob containers."""

    OPERATIONS = auto()
    FULL_TEXTS = auto()


_CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "jsonl": "application/jsonl",
    "json": "application/json",
    "csv": "text/csv",
    "txt": "text/plain",
    "pdf": "application/pdf",
    "xml": "application/xml",
    "html": "text/html",
}


class BlobStorageFile(BaseModel):
    """Model to represent Blob Storage files."""

    location: BlobStorageLocation = Field(
        description="The location of the blob storage.",
    )
    container: str = Field(
        pattern=r"^[^/]*$",  # Ensure no slashes are present
        description="The name of the container in blob storage.",
    )
    path: str = Field(
        description="The path to the file in blob storage.",
    )
    filename: str = Field(
        pattern=r"^[^/]*$",  # Ensure no slashes are present
        description="The name of the file in blob storage.",
    )
    content_type: str | None = Field(
        default=None,
        description=(
            "The content type of the file, e.g. 'application/jsonl'. "
            "If not provided, it will be inferred from the file extension."
        ),
    )

    @property
    def scheme(self) -> str:
        """URI scheme for this blob. REMOTE blobs are always https."""
        return (
            "https"
            if self.location == BlobStorageLocation.REMOTE
            else self.location.value
        )

    @model_validator(mode="before")
    @classmethod
    def _coerce_and_default(cls, value: object) -> object:
        """Accept a URI string; default content_type from filename extension."""
        if isinstance(value, str):
            return cls._parse_uri(value)
        if not isinstance(value, dict):
            return value

        if not value.get("content_type"):
            filename = value.get("filename") or ""
            extension = (
                filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
            )
            content_type = _CONTENT_TYPE_BY_EXTENSION.get(extension)
            if content_type is None:
                logger.warning(
                    "No content type defined. Defaulting to application/octet-stream.",
                    filename=filename,
                )
                content_type = "application/octet-stream"
            value["content_type"] = content_type
        return value

    def to_uri(self) -> str:
        """Return the URI representation of the file."""
        path_segment = f"{self.path}/{self.filename}" if self.path else self.filename
        return f"{self.scheme}://{self.container}/{path_segment}"

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Populate the model from its URI representation."""
        return cls(**cls._parse_uri(uri))

    @classmethod
    def _parse_uri(cls, uri: str) -> dict[str, object]:
        """Parse a URI string into kwargs for construction."""
        scheme, _, rest = uri.partition("://")
        parts = rest.split("/")
        if len(parts) < 2:  # noqa: PLR2004
            msg = f"Invalid blob URI {uri!r} for BlobStorageFile."
            raise BlobStorageError(msg)
        try:
            location = (
                BlobStorageLocation.REMOTE
                if scheme == "https"
                else BlobStorageLocation(scheme)
            )
        except ValueError as e:
            msg = f"Invalid blob URI {uri!r}: unknown scheme {scheme!r}."
            raise BlobStorageError(msg) from e
        return {
            "location": location,
            "container": parts[0],
            "path": "/".join(parts[1:-1]),
            "filename": parts[-1],
        }

    @model_serializer(mode="plain", when_used="json")
    def _serialize_to_uri(self) -> str:
        """Serialize to a URI string when dumping in JSON mode."""
        return self.to_uri()

    model_config = ConfigDict(frozen=True)


class BlobCopyResult(BaseModel):
    """Model to represent the result of copying a blob storage file."""

    source: BlobStorageFile = Field(
        description="The source file that was copied.",
    )
    destination: BlobStorageFile = Field(
        description="The destination file that was copied to.",
    )
    byte_size: int = Field(
        description="The size of the copied file in bytes.",
    )
    sha256_checksum: str = Field(
        description="The SHA256 checksum of the copied file.",
    )
