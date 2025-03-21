"""Models used by the `Import` domain."""

import datetime
import uuid
from enum import StrEnum

from pydantic import (
    Field,
    HttpUrl,
    PastDatetime,
)

from app.domain.base import DomainBaseModel


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
    COMPLETED = "completed"
    CANCELLED = "cancelled"


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
    status: ImportRecordStatus = Field(
        ImportRecordStatus.CREATED,
        description="""
The status of the upload.
""",
    )


class ImportRecord(ImportRecordBase):
    """Import Record model for database use."""

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="""
The ID of the import, which may be set by the processor or will be generated
on creation.
""",
    )
    batches: list["ImportBatch"] = Field(
        default=[], description="The batches derived from this import."
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

    import_record_id: uuid.UUID = Field(
        description="The ID of the parent import record."
    )
    status: ImportBatchStatus = Field(
        default=ImportBatchStatus.CREATED, description="The status of the batch."
    )
    storage_url: HttpUrl = Field(
        description="""
The URL at which the set of references for this batch are stored.
    """,
    )


class ImportBatch(ImportBatchBase):
    """Import Batch model for database use."""

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="""
The identifier of the batch, which may be set by the processor or will be
generated on creation.
""",
    )

    import_record: ImportRecord = Field(description="The parent import record.")


class ImportBatchCreate(ImportBatchBase):
    """Input for creating an import batch."""
