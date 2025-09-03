"""Models used by the `Import` domain."""

import datetime
import uuid
from enum import StrEnum, auto

from pydantic import Field, HttpUrl, PastDatetime

from app.domain.base import DomainBaseModel, SQLAttributeMixin


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


class ImportBatch(DomainBaseModel, SQLAttributeMixin):
    """Core import batch model with database and internal attributes included."""

    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored.
    """,
    )
    callback_url: HttpUrl | None = Field(
        default=None,
        description="""
The URL to which the processor should send a callback when the batch has been processed.
        """,
    )
    status: ImportBatchStatus = Field(
        default=ImportBatchStatus.CREATED, description="The status of the batch."
    )
    import_record_id: uuid.UUID = Field(
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

    import_batch_id: uuid.UUID = Field(description="The ID of the parent import batch.")
    status: ImportResultStatus = Field(
        default=ImportResultStatus.CREATED, description="The status of the result."
    )
    import_batch: ImportBatch | None = Field(
        default=None, description="The parent import batch."
    )
    reference_id: uuid.UUID | None = Field(
        default=None, description="The ID of the created reference."
    )
    failure_details: str | None = Field(
        default=None,
        description="Details of any failure that occurred during processing.",
    )
