"""Reference classes for the Destiny SDK."""

from enum import StrEnum, auto
from typing import Self

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter

from destiny_sdk.core import UUID, SearchResultMixIn, _JsonlFileInputMixIn
from destiny_sdk.enhancements import Enhancement, EnhancementFileInput
from destiny_sdk.identifiers import ExternalIdentifier
from destiny_sdk.search import SearchResultTotal
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


class ReferenceIDSearchResult(BaseModel):
    """The matching reference IDs for a search, without the reference data."""

    total: SearchResultTotal = Field(
        description="The total number of references matching the search criteria."
    )
    reference_ids: list[UUID] = Field(
        description="The IDs of the references matching the search, in result order."
    )


class FacetType(StrEnum):
    """Search facets of references."""

    CONCEPTS = auto()
    """Counts of references per linked-data concept URI."""
    COUNTRIES = auto()
    """Counts of references per ISO 3166-1 alpha-2 country code."""
    COUNTRY_WB_REGIONS = auto()
    """Counts of references per World Bank region ID."""


class ConceptFacetCount(BaseModel):
    """The count of matching references for a single concept."""

    concept: str = Field(description="The concept URI.")
    count: int = Field(
        description="Number of matching references tagged with this concept.",
    )


class CountryFacetCount(BaseModel):
    """The count of matching references for a single country."""

    country: str = Field(description="The ISO 3166-1 alpha-2 country code.")
    count: int = Field(
        description="Number of matching references tagged with this country.",
    )


class CountryWBRegionFacetCount(BaseModel):
    """The count of matching references for a single World Bank region."""

    country_wb_region: str = Field(description="The World Bank region ID.")
    count: int = Field(
        description="Number of matching references tagged with this region.",
    )


class ReferenceFacetResult(BaseModel):
    """Facet counts for a reference search."""

    concepts: list[ConceptFacetCount] | None = Field(
        default=None,
        description="Counts of matching references per linked-data concept URI.",
    )
    countries: list[CountryFacetCount] | None = Field(
        default=None,
        description=(
            "Counts of matching references per ISO 3166-1 alpha-2 country code."
        ),
    )
    country_wb_regions: list[CountryWBRegionFacetCount] | None = Field(
        default=None,
        description="Counts of matching references per World Bank region ID.",
    )


class CrossFacetCell(BaseModel):
    """A single non-zero cell of a cross-facet (cross-tabulation) matrix."""

    axes: tuple[str, str] = Field(
        description=(
            "The cell's value on each axis, in the same order as the requested "
            "`axes`. Each value is a concept URI (for a concept-scheme axis) or a "
            "code (for a country/region axis)."
        ),
    )
    count: int = Field(
        description=(
            "Number of references matching both axis values together, under all "
            "filters and the query string."
        ),
    )


class ReferenceCrossFacetResult(BaseModel):
    """
    Cross-tabulation of two axes over the references matching a search.

    Each cell counts references at the strict intersection of its two axis values,
    all panel filters, and the query string. Only non-zero cells are returned.

    Note: cells may sum to more than ``total`` because a reference can carry multiple
    values on a single axis, so it contributes to multiple cells.
    """

    total: SearchResultTotal = Field(
        description="The total number of references matching the search criteria.",
    )
    cells: list[CrossFacetCell] = Field(
        description="The non-zero cells of the cross-facet matrix.",
    )


class ExportFormat(StrEnum):
    """The serialization format of a reference export."""

    JSONL = auto()
    """JSON Lines: one reference per line."""
    RIS = auto()
    """RIS: tagged citation format."""

    @property
    def extension(self) -> str:
        """The file extension for this format."""
        return self.value


class SearchExportStatus(StrEnum):
    """The status of a search export job."""

    PENDING = auto()
    """The export job has been queued but not yet started."""
    RUNNING = auto()
    """The export job is currently being processed."""
    COMPLETED = auto()
    """The export job completed and the file is available."""
    FAILED = auto()
    """The export job failed before producing a file."""


class SearchExportRead(BaseModel):
    """A search export job, used to poll for status and a signed URL."""

    id: UUID = Field(description="The ID of the export job.")
    status: SearchExportStatus = Field(
        description="The current status of the export job.",
    )
    export_format: ExportFormat = Field(
        default=ExportFormat.JSONL,
        description="The serialization format of the produced file.",
    )
    result_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Signed download URL for the produced file. Populated once ``status`` "
            "is ``completed``; the URL is re-signed on every poll, so an expired "
            "URL can be refreshed by polling again."
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
