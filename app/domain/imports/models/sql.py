"""
SQL models used by the `Import` domain.

These models should only be accessed through the DTO.
"""

import datetime
import uuid

from sqlalchemy import UUID, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.imports.models.models import ImportBatchStatus, ImportRecordStatus
from app.persistence.sql.declarative_base import Base


class ImportRecord(Base):
    """SQL model for an individual import record."""

    __tablename__ = "import_record"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    search_string: Mapped[str | None] = mapped_column(
        String,
    )
    searched_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    processor_name: Mapped[str] = mapped_column(String, nullable=False)
    processor_version: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(String)
    expected_reference_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ImportRecordStatus] = mapped_column(
        ENUM(
            *[status.value for status in ImportRecordStatus],
            name="import_record_status",
        ),
        nullable=False,
    )

    batches: Mapped[list["ImportBatch"]] = relationship(
        "ImportBatch", back_populates="import_record"
    )


class ImportBatch(Base):
    """SQL model for an individual import batch."""

    __tablename__ = "import_batch"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    import_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("import_record.id"), nullable=False
    )
    status: Mapped[ImportBatchStatus] = mapped_column(
        ENUM(
            *[status.value for status in ImportBatchStatus],
            name="import_batch_status",
        ),
        nullable=False,
    )
    storage_url: Mapped[str] = mapped_column(String, nullable=False)

    import_record: Mapped[ImportRecord] = relationship(
        "ImportRecord", back_populates="batches"
    )
