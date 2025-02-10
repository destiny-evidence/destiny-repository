"""Model describing import records."""

import uuid
from enum import Enum, auto

from pydantic import PastDatetime
from sqlalchemy import TIMESTAMP, Column
from sqlmodel import Field, SQLModel


class ImportStatus(str, Enum):
    """Used to describe the status of an `Import`."""

    created = auto()
    started = auto()
    completed = auto()
    cancelled = auto()


class ImportRecordBase(SQLModel):
    """Base model of ImportRecords without db-only fields."""

    search_string: str
    searched_at: PastDatetime = Field(sa_column=Column(TIMESTAMP(timezone=True)))
    processor_name: str
    processor_version: str
    notes: str
    expected_record_count: int
    source_name: str
    status: str = ImportStatus.created


class ImportRecord(ImportRecordBase, table=True):
    """Database model for Import Records."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class ImportRecordCreate(ImportRecordBase):
    """Input for creating an import record."""
