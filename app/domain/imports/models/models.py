"""Models used by the `Import` domain."""

import datetime
from enum import StrEnum, auto

from pydantic import UUID4, UUID7, Field, HttpUrl, PastDatetime

from app.domain.base import DomainBaseModel, ProjectedBaseModel, SQLAttributeMixin


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
    The reference was created but one or more enhancements or identifiers failed to be
    added. See the result's `failure_details` field for more information.
    """
    FAILED = auto()
    """
    The reference failed to be created. See the result's `failure_details` field for
    more information.
    """
    RETRYING = auto()
    """Processing has failed, but is being retried."""


class ImportRecord(DomainBaseModel, SQLAttributeMixin):
    """Core import record model with database and internal attributes included."""

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

    status: ImportRecordStatus = Field(
        default=ImportRecordStatus.CREATED,
        description="The status of the upload.",
    )
    batches: list["ImportBatch"] | None = Field(
        default=None, description="The batches associated with this import."
    )


class ImportBatch(DomainBaseModel, ProjectedBaseModel, SQLAttributeMixin):
    """Core import batch model with database and internal attributes included."""

    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored.
    """,
    )
    status: ImportBatchStatus | None = Field(
        default=None, description="The status of the batch."
    )
    import_record_id: UUID4 | UUID7 = Field(
        description="The ID of the parent import record."
    )
    import_record: ImportRecord | None = Field(
        default=None, description="The parent import record."
    )
    import_results: list["ImportResult"] | None = Field(
        default=None, description="The results from processing the batch."
    )


class ImportResult(DomainBaseModel, SQLAttributeMixin):
    """Core import result model with database attributes included."""

    import_batch_id: UUID4 | UUID7 = Field(
        description="The ID of the parent import batch."
    )
    status: ImportResultStatus = Field(
        default=ImportResultStatus.CREATED, description="The status of the result."
    )
    import_batch: ImportBatch | None = Field(
        default=None, description="The parent import batch."
    )
    reference_id: UUID4 | UUID7 | None = Field(
        default=None, description="The ID of the created reference."
    )
    failure_details: str | None = Field(
        default=None,
        description="Details of any failure that occurred during processing.",
    )
