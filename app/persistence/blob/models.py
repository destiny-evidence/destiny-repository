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


class BlobSignedUrlType(StrEnum):
    """Blob Storage interaction types."""

    DOWNLOAD = auto()
    UPLOAD = auto()


class BlobStorageLocation(StrEnum):
    """Blob Storage locations."""

    AZURE = auto()
    MINIO = auto()
    HTTP = auto()
    HTTPS = auto()

    @classmethod
    def remote(cls) -> frozenset["BlobStorageLocation"]:
        """Return the set of remote blob storage locations."""
        return frozenset({cls.HTTP, cls.HTTPS})


class BlobContainer(StrEnum):
    """Blob containers."""

    OPERATIONS = auto()
    FULL_TEXTS = auto()


_CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "jsonl": "application/jsonl",
    "ris": "application/x-research-info-systems",
    "json": "application/json",
    "csv": "text/csv",
    "txt": "text/plain",
    "pdf": "application/pdf",
    "xml": "application/xml",
    "html": "text/html",
}


def infer_content_type(filename: str) -> str:
    """
    Infer the MIME content type for ``filename`` from its extension.

    Falls back to ``application/octet-stream`` for unknown extensions.
    """
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    return _CONTENT_TYPE_BY_EXTENSION.get(extension, "application/octet-stream")


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

    @property
    def is_remote(self) -> bool:
        """Whether this blob lives at a URL we don't own (http/https)."""
        return self.location in BlobStorageLocation.remote()

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_uri(cls, value: object) -> object:
        """Accept a URI string in place of a dict for validation."""
        if isinstance(value, str):
            return cls._parse_uri(value)
        return value

    def to_uri(self) -> str:
        """Return the URI representation of the file."""
        path_segment = f"{self.path}/{self.filename}" if self.path else self.filename
        return f"{self.location.value}://{self.container}/{path_segment}"

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
            location = BlobStorageLocation(scheme)
        except ValueError as e:
            msg = f"Invalid blob URI {uri!r}: unknown scheme {scheme!r}."
            raise BlobStorageError(msg) from e
        return {
            "location": location,
            "container": parts[0],
            "path": "/".join(parts[1:-1]),  # empty string if no path
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
