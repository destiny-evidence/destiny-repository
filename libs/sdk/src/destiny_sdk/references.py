"""Reference classes for the Destiny SDK."""

from enum import StrEnum, auto
from typing import Self

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter

from destiny_sdk.core import UUID, SearchResultMixIn, _JsonlFileInputMixIn
from destiny_sdk.enhancements import Enhancement, EnhancementFileInput
from destiny_sdk.identifiers import ExternalIdentifier
from destiny_sdk.visibility import Visibility

external_identifier_adapter: TypeAdapter[ExternalIdentifier] = TypeAdapter(
    ExternalIdentifier
)


class Reference(_JsonlFileInputMixIn, BaseModel):
    """Core reference class."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    id: UUID = Field(
        description="The ID of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[Enhancement] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )

    @classmethod
    def from_es(cls, es_reference: dict) -> Self:
        """Create a Reference from an Elasticsearch document."""
        return cls(
            id=es_reference["_id"],
            visibility=Visibility(es_reference["_source"]["visibility"]),
            identifiers=[
                external_identifier_adapter.validate_python(identifier)
                for identifier in es_reference["_source"].get("identifiers", [])
            ],
            enhancements=[
                Enhancement.model_validate(
                    enhancement | {"reference_id": es_reference["_id"]},
                )
                for enhancement in es_reference["_source"].get("enhancements", [])
            ],
        )


class ReferenceFileInput(_JsonlFileInputMixIn, BaseModel):
    """Enhancement model used to marshall a file input."""

    visibility: Visibility = Field(
        default=Visibility.PUBLIC,
        description="The level of visibility of the reference",
    )
    identifiers: list[ExternalIdentifier] | None = Field(
        default=None,
        description="A list of `ExternalIdentifiers` for the Reference",
    )
    enhancements: list[EnhancementFileInput] | None = Field(
        default=None,
        description="A list of enhancements for the reference",
    )


class ReferenceSearchResult(SearchResultMixIn, BaseModel):
    """A search result for references."""

    references: list[Reference] = Field(
        description="The references returned by the search.",
    )


class ReferenceExportStatus(StrEnum):
    """The status of a reference export job."""

    PENDING = auto()
    """The export job has been queued but not yet started."""
    RUNNING = auto()
    """The export job is currently being processed."""
    COMPLETED = auto()
    """The export job completed and the file is available."""
    FAILED = auto()
    """The export job failed before producing a file."""


class ReferenceExportRead(BaseModel):
    """A reference export job, used to poll for status and a signed URL."""

    id: UUID = Field(description="The ID of the export job.")
    status: ReferenceExportStatus = Field(
        description="The current status of the export job.",
    )
    result_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Signed download URL for the produced JSONL file. Each line is a "
            ":class:`Reference <destiny_sdk.references.Reference>` "
            "matching the `/references/search/` response shape. Populated once "
            "``status`` is ``completed``; the URL is re-signed on every poll, so "
            "an expired URL can be refreshed by polling again."
        ),
    )
    n_references: int | None = Field(
        default=None,
        description="The number of references included in the produced file.",
    )
    truncated: bool = Field(
        default=False,
        description=(
            "Whether the matching result set exceeded the server's result-window "
            "cap. When true, the JSONL contains only the first window's worth of "
            "matches."
        ),
    )
    error: str | None = Field(
        default=None,
        description="Error encountered while producing the export.",
    )
