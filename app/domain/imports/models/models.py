"""Models used by the `Import` domain."""

import datetime
import uuid
from enum import StrEnum

from pydantic import (
    Field,
    HttpUrl,
    PastDatetime,
)

from app.domain.base import DomainBaseModel, SQLAttributeMixin


class ImportRecordStatus(StrEnum):
    """
    Describes the status of an import record.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = "created"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ImportBatchStatus(StrEnum):
    """
    Describes the status of an import batch.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    CREATED = "created"
    STARTED = "started"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CollisionStrategy(StrEnum):
    """
    The strategy to use when an identifier collision is detected.

    **Allowed values**:
    - `discard`: Do nothing with the incoming reference.
    - `fail`: Do nothing with the incoming reference and mark it as failed. This
        allows the importing process to "follow up" on the failure.
    - `overwrite`: Delete the existing reference and replace it with the incoming
        reference.
    - `merge_aggressive`: Prioritize the incoming reference by preserving all
        incoming fields and supplementing them with any matching values from the
        existing reference.
    - `merge_defensive`: Prioritize the existing reference by preserving all existing
        fields while incorporating non-conflicting data from the incoming reference.
    """

    DISCARD = "discard"
    FAIL = "fail"
    OVERWRITE = "overwrite"
    MERGE_AGGRESSIVE = "merge_aggressive"
    MERGE_DEFENSIVE = "merge_defensive"


class ImportResultStatus(StrEnum):
    """
    Describes the status of an import result.

    - `created`: Created, but no processing has started.
    - `started`: The reference is currently being processed.
    - `completed`: The reference has been created.
    - `cancelled`: Processing was cancelled by calling the API.
    - `partially_failed`: The reference was created but one or more enhancements or
        identifiers failed to be added. See the result's `failure_details` field for
        more information.
    - `failed`: The reference failed to be created.
        See the result's `failure_details` field for more information.
    """

    CREATED = "created"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class ImportRecordBase(DomainBaseModel):
    """
    The base model for Import Records.

    An Import Record is essentially an accounting record for imports into the
    data repo. It allows us to understand the provenance of records and keep track
    of the processing of imports as well as the resulting creation or update of
    references within the repo.

    """

    search_string: str | None = Field(
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
        description="""
Any additional notes regarding the import (eg. reason for importing, known
issues).
        """,
    )
    expected_reference_count: int = Field(
        description="The number of references expected to be included in this import."
    )
    source_name: str = Field(
        description="The source of the reference being imported (eg. Open Alex)"
    )


class ImportRecord(ImportRecordBase, SQLAttributeMixin):
    """Core import record model with database and internal attributes included."""

    status: ImportRecordStatus = Field(
        default=ImportRecordStatus.CREATED,
        description="The status of the upload.",
    )
    batches: list["ImportBatch"] | None = Field(
        None, description="The batches associated with this import."
    )


class ImportRecordCreate(ImportRecordBase):
    """Input for creating an import record."""


class ImportBatchBase(DomainBaseModel):
    """
    The base class for import batches.

    An import batch is a set of references imported together as part of a larger
    import. They wrap a storage URL and track the status of the importing of the
    file at that storage url.
    """

    collision_strategy: CollisionStrategy = Field(
        default=CollisionStrategy.FAIL,
        description="""
The strategy to use for each reference when an identifier collision occurs.
Default is `fail`, which allows the importing process to "follow up" on the collision.
        """,
    )
    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored.
    """,
    )


class ImportBatch(ImportBatchBase, SQLAttributeMixin):
    """Core import batch model with database and internal attributes included."""

    status: ImportBatchStatus = Field(
        default=ImportBatchStatus.CREATED, description="The status of the batch."
    )
    import_record_id: uuid.UUID = Field(
        description="The ID of the parent import record."
    )
    import_record: ImportRecord | None = Field(
        None, description="The parent import record."
    )
    import_results: list["ImportResult"] | None = Field(
        None, description="The results from processing the batch."
    )


class ImportBatchCreate(ImportBatchBase):
    """Input for creating an import batch."""


class ImportResultBase(DomainBaseModel):
    """
    The base class for import results.

    An import result is a record of the outcome of a single imported reference.
    It is essentially a "Reference attempt".
    These are created during the processing of an ImportBatch file.
    """

    import_batch_id: uuid.UUID = Field(description="The ID of the parent import batch.")
    status: ImportResultStatus = Field(
        default=ImportResultStatus.CREATED, description="The status of the result."
    )


class ImportResult(ImportResultBase, SQLAttributeMixin):
    """Core import result model with database attributes included."""

    import_batch: ImportBatch | None = Field(
        None, description="The parent import batch."
    )
    reference_id: uuid.UUID | None = Field(
        None, description="The ID of the created reference."
    )
    failure_details: str | None = Field(
        None, description="Details of any failure that occurred during processing."
    )


class ImportResultCreate(ImportResultBase):
    """Input for creating an import result."""


class ImportBatchSummary(ImportBatchBase):
    """A view for an import batch that includes a summary of its results."""

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="""
The identifier of the batch, which may be set by the processor or will be
generated on creation.
""",
    )

    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC),
        description="The timestamp at which the batch was created.",
    )
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC),
        description="The timestamp at which the batch's status was last updated.",
    )

    results: dict[ImportResultStatus, int] = Field(
        description="A count of references by their current import status."
    )
    failure_details: list[str] | None = Field(
        description="The details of the failures that occurred.",
    )
