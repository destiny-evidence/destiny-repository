"""Import process classes for the Destiny SDK."""

import datetime
from enum import StrEnum, auto

from pydantic import (
    UUID4,
    BaseModel,
    Field,
    HttpUrl,
    PastDatetime,
)


class ImportRecordStatus(StrEnum):
    """Describes the status of an import record."""

    CREATED = auto()
    """Created, but no processing has started."""
    STARTED = auto()
    """Processing has started on the batch."""
    COMPLETED = auto()
    """Processing has been completed."""


class ImportBatchStatus(StrEnum):
    """Describes the status of an import batch."""

    CREATED = auto()
    """Created, but no processing has started."""
    STARTED = auto()
    """Processing has started on the batch."""
    FAILED = auto()
    """Processing has failed."""
    PARTIALLY_FAILED = auto()
    """Some references succeeded while others failed."""
    COMPLETED = auto()
    """Processing has been completed."""


class ImportResultStatus(StrEnum):
    """Describes the status of an import result."""

    CREATED = auto()
    """Created, but no processing has started."""
    STARTED = auto()
    """The reference is currently being processed."""
    COMPLETED = auto()
    """The reference has been created."""
    PARTIALLY_FAILED = auto()
    """
    The reference was created but one or more enhancements or identifiers failed to
    be added. See the result's `failure_details` field for more information.
    """
    FAILED = auto()
    """
    The reference failed to be created. See the result's `failure_details` field for
    more information.
    """
    RETRYING = auto()
    """Processing has failed, but is being retried."""


class _ImportRecordBase(BaseModel):
    """Base import record class."""

    search_string: str | None = Field(
        default=None,
        description="The search string used to produce this import",
    )
    searched_at: PastDatetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC),
        description="""
The timestamp (including timezone) at which the search which produced
this import was conducted. If no timezone is included, the timestamp
is assumed to be in UTC.
        """,
    )
    processor_name: str = Field(
        description="The name of the processor that is importing the data."
    )
    processor_version: str = Field(
        description="The version of the processor that is importing the data."
    )
    notes: str | None = Field(
        default=None,
        description="""
Any additional notes regarding the import (eg. reason for importing, known
issues).
        """,
    )
    expected_reference_count: int = Field(
        description="""
The number of references expected to be included in this import.
-1 is accepted if the number is unknown.
""",
        ge=-1,
    )
    source_name: str = Field(
        description="The source of the reference being imported (eg. Open Alex)"
    )


class ImportRecordIn(_ImportRecordBase):
    """Input for creating an import record."""


class ImportRecordRead(_ImportRecordBase):
    """Core import record class."""

    id: UUID4 = Field(
        description="The ID of the import record",
    )
    status: ImportRecordStatus = Field(
        ImportRecordStatus.CREATED,
        description="The status of the import record",
    )
    batches: list["ImportBatchRead"] | None = Field(
        default=None,
        description="A list of batches for the import record",
    )


class _ImportBatchBase(BaseModel):
    """The base class for import batches."""

    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored. The file is a jsonl
with each line formatted according to
:class:`ReferenceFileInput <libs.sdk.src.destiny_sdk.references.ReferenceFileInput>`.
    """,
    )


class ImportBatchIn(_ImportBatchBase):
    """Input for creating an import batch."""


class ImportBatchRead(_ImportBatchBase):
    """Core import batch class."""

    id: UUID4 = Field(
        description="The ID of the import batch",
    )
    status: ImportBatchStatus = Field(
        default=ImportBatchStatus.CREATED, description="The status of the batch."
    )
    import_record_id: UUID4 = Field(
        description="The ID of the import record this batch is associated with"
    )
    import_record: ImportRecordRead | None = Field(
        default=None, description="The parent import record."
    )
    import_results: list["ImportResultRead"] | None = Field(
        default=None, description="The results from processing the batch."
    )


class ImportBatchSummary(_ImportBatchBase):
    """A view for an import batch that includes a summary of its results."""

    id: UUID4 = Field(
        description="""
The identifier of the batch.
""",
    )

    import_batch_id: UUID4 = Field(description="The ID of the batch being summarised")

    import_batch_status: ImportBatchStatus = Field(
        description="The status of the batch being summarised"
    )

    results: dict[ImportResultStatus, int] = Field(
        description="A count of references by their current import status."
    )
    failure_details: list[str] | None = Field(
        description="""
        The details of the failures that occurred.
        Each failure will start with `"Entry x"` where x is the line number of the
        jsonl object attempted to be imported.
        """,
    )


class ImportResultRead(BaseModel):
    """Core import result class."""

    id: UUID4 = Field(description="The ID of the import result.")
    reference_id: UUID4 | None = Field(
        default=None,
        description="The ID of the reference created by this import result.",
    )
    failure_details: str | None = Field(
        default=None,
        description="The details of the failure, if the import result failed.",
    )
    import_batch: ImportBatchRead | None = Field(
        default=None, description="The parent import batch."
    )
