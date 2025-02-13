"""Models for import batches."""

import uuid
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from pydantic import HttpUrl
from sqlmodel import AutoString, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.import_record import ImportRecord


class ImportBatchStatus(str, Enum):
    """Describes the status of an import batch."""

    created = auto()
    started = auto()
    completed = auto()
    cancelled = auto()


class ImportBatch(SQLModel, table=True):
    """The base class for import batches."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    import_id: uuid.UUID | None = Field(default=None, foreign_key="importrecord.id")
    import_record: Optional["ImportRecord"] = Relationship(back_populates="batches")
    status: ImportBatchStatus = ImportBatchStatus.created
    storage_url: HttpUrl = Field(..., sa_type=AutoString)
