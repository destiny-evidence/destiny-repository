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
    """
    Describes the status of an import record.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class ImportBatchStatus(StrEnum):
    """
    Describes the status of an import batch.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `failed`: Processing has failed.
    - `retrying`: Processing has failed, but is being retried.
    - `indexing`: The imports have been saved and are being indexed.
    - `indexing_failed`: The imports have been saved but were not indexed.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    RETRYING = auto()
    FAILED = auto()
    INDEXING = auto()
    INDEXING_FAILED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class CollisionStrategy(StrEnum):
    """
    The strategy to use when an identifier collision is detected.

    Identifier collisions are detected on ``identifier_type`` and ``identifier``
    (and ``other_identifier_name`` where relevant) already present in the database.

    Enhancement collisions are detected on an entry with matching ``enhancement_type``
    and ``source`` already being present on the collided reference.

    - `discard`: Do nothing with the incoming reference.
    - `fail`: Do nothing with the incoming reference and mark it as failed. This
      allows the importing process to "follow up" on the failure.
    - `merge_aggressive`: Prioritize the incoming reference's identifiers and
      enhancements in the merge.
    - `merge_defensive`: Prioritize the existing reference's identifiers and
      enhancements in the merge.
    - `append`: Performs an aggressive merge of identifiers, and an append of
      enhancements.
    - `overwrite`: Performs an aggressive merge of identifiers, and an overwrite of
      enhancements (deleting existing and recreating what is imported). This should
      be used sparingly and carefully.
    """

    DISCARD = auto()
    FAIL = auto()
    MERGE_AGGRESSIVE = auto()
    MERGE_DEFENSIVE = auto()
    APPEND = auto()
    OVERWRITE = auto()


class ImportResultStatus(StrEnum):
    """
    Describes the status of an import result.

    - `created`: Created, but no processing has started.
    - `started`: The reference is currently being processed.
    - `completed`: The reference has been created.
    - `partially_failed`: The reference was created but one or more enhancements or
      identifiers failed to be added. See the result's `failure_details` field for
      more information.
    - `failed`: The reference failed to be created. See the result's `failure_details`
      field for more information.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = auto()
    STARTED = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    PARTIALLY_FAILED = auto()
    FAILED = auto()


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

    collision_strategy: CollisionStrategy = Field(
        default=CollisionStrategy.FAIL,
        description="""
The strategy to use for each reference when an identifier collision occurs.
Default is `fail`, which allows the importing process to "follow up" on the collision.
        """,
    )
    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored. The file is a jsonl
with each line formatted according to
:class:`ReferenceFileInput <libs.sdk.src.destiny_sdk.references.ReferenceFileInput>`.
    """,
    )
    callback_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL to which the processor should send a callback when the batch has been processed.
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
