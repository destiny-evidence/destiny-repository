"""Models for import batches."""

import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import HttpUrl
from sqlmodel import AutoString, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.import_record import ImportRecord


class ImportBatchStatus(str, Enum):
    """
    Describes the status of an import batch.

    - `created`: Created, but no processing has started.
    - `started`: Processing has started on the batch.
    - `completed`: Processing has been completed.
    - `cancelled`: Processing was cancelled by calling the API.
    """

    created = "created"
    started = "started"
    completed = "completed"
    cancelled = "cancelled"


class ImportBatch(SQLModel, table=True):
    """
    The base class for import batches.

    An import batch is a set of references imported together as part of a larger
    import. They wrap a storage URL and track the status of the importing of the
    file at that storage url.
    """

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="""
The identifier of the batch, which may be set by the processor or will be
generated on creation.
""",
    )
    import_id: uuid.UUID | None = Field(default=None, foreign_key="importrecord.id")
    import_record: Optional["ImportRecord"] = Relationship(back_populates="batches")
    status: ImportBatchStatus = ImportBatchStatus.created
    storage_url: HttpUrl = Field(..., sa_type=AutoString)
