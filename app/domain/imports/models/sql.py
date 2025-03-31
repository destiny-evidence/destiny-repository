"""Data transfer objects used to interface between domain and persistence models."""

import asyncio
import datetime
import uuid
from typing import Self

from pydantic import HttpUrl
from sqlalchemy import UUID, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportBatchStatus,
    ImportRecordStatus,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.persistence.sql.persistence import GenericSQLPersistence


class ImportBatch(GenericSQLPersistence[DomainImportBatch]):
    """
    SQL Persistence model for an ImportBatch.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "import_batch"

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

    import_record: Mapped["ImportRecord"] = relationship(
        "ImportRecord", back_populates="batches"
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportBatch) -> Self:
        """Create a persistence model from a domain ImportBatch object."""
        return cls(
            id=domain_obj.id,
            import_record_id=domain_obj.import_record_id,
            status=domain_obj.status,
            storage_url=str(domain_obj.storage_url),
        )

    async def to_domain(self, preload: list[str] | None = None) -> DomainImportBatch:
        """Convert the persistence model into an Domain ImportBatch object."""
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=HttpUrl(self.storage_url),
            import_record=await self.import_record.to_domain()
            if "import_record" in (preload or [])
            else None,
        )


class ImportRecord(GenericSQLPersistence[DomainImportRecord]):
    """
    SQL Persistence model for an ImportRecord.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "import_record"

    search_string: Mapped[str | None] = mapped_column(
        String,
    )
    searched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
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

    batches: Mapped[list[ImportBatch]] = relationship(
        "ImportBatch", back_populates="import_record"
    )

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportRecord) -> Self:
        """Create a persistence model from a domain ImportRecord object."""
        return cls(
            id=domain_obj.id,
            search_string=domain_obj.search_string,
            searched_at=domain_obj.searched_at,
            processor_name=domain_obj.processor_name,
            processor_version=domain_obj.processor_version,
            notes=domain_obj.notes,
            expected_reference_count=domain_obj.expected_reference_count,
            source_name=domain_obj.source_name,
            status=domain_obj.status,
        )

    async def to_domain(self, preload: list[str] | None = None) -> DomainImportRecord:
        """Convert the persistence model into an Domain ImportRecord object."""
        if preload is None:
            preload = []
        return DomainImportRecord(
            id=self.id,
            search_string=self.search_string,
            searched_at=self.searched_at,
            processor_name=self.processor_name,
            processor_version=self.processor_version,
            notes=self.notes,
            expected_reference_count=self.expected_reference_count,
            source_name=self.source_name,
            status=self.status,
            batches=await asyncio.gather(*(batch.to_domain() for batch in self.batches))
            if "batches" in (preload or [])
            else None,
        )
