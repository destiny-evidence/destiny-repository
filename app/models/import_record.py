"""Model describing import records."""

import uuid
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import PastDatetime
from sqlalchemy import TIMESTAMP, Column
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.import_batch import ImportBatch


class ImportStatus(str, Enum):
    """Used to describe the status of an `Import`."""

    created = "created"
    started = "started"
    completed = "completed"
    cancelled = "cancelled"


class ImportRecordBase(SQLModel):
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
        ...,
        description="""
The timestamp (including timezone) at which the search which produced
this import was conducted. If no timezone is included, the timestamp
is assumed to be in UTC.
        """,
        sa_column=Column(TIMESTAMP(timezone=True)),
    )
    processor_name: str = Field(
        ..., description="The name of the processor that is importing the data."
    )
    processor_version: str = Field(
        ..., description="The version of the processor that is importing the data."
    )
    notes: str | None = Field(
        ...,
        description="""
Any additional notes regarding the import (eg. reason for importing, known
issues).
        """,
    )
    expected_record_count: int = Field(
        ..., description="The number of records expected to be included in this import."
    )
    source_name: str = Field(
        ..., description="The source of the records being imported (eg. Open Alex)"
    )
    status: ImportStatus = Field(
        ImportStatus.created,
        description="""
The status of the upload (read-only).
""",
    )


class ImportRecord(ImportRecordBase, AsyncAttrs, table=True):
    """Import Record model for database use."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    batches: list["ImportBatch"] = Relationship(back_populates="import_record")


class ImportRecordCreate(ImportRecordBase):
    """Input for creating an import record."""
