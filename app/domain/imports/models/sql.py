"""Objects used to interface with SQL implementations."""

import datetime
from typing import Self
from uuid import UUID

from pydantic import HttpUrl
from sqlalchemy import (
    UUID as SQL_UUID,
)
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.models import (
    ImportRecordStatus,
    ImportResultStatus,
)
from app.domain.imports.models.models import (
    ImportResult as DomainImportResult,
)
from app.persistence.sql.generics import GenericSQLPreloadableType
from app.persistence.sql.persistence import GenericSQLPersistence


class ImportResult(GenericSQLPersistence[DomainImportResult]):
    """SQL model for an individual import result."""

    __tablename__ = "import_result"

    import_batch_id: Mapped[UUID] = mapped_column(
        SQL_UUID, ForeignKey("import_batch.id"), nullable=False
    )
    status: Mapped[ImportResultStatus] = mapped_column(
        ENUM(
            *[status.value for status in ImportResultStatus],
            name="import_result_status",
        ),
        nullable=False,
    )
    reference_id: Mapped[UUID | None] = mapped_column(SQL_UUID)
    failure_details: Mapped[str | None] = mapped_column(String)

    import_batch: Mapped["ImportBatch"] = relationship(
        "ImportBatch", back_populates="import_results"
    )

    __table_args__ = (
        Index("ix_import_result_import_batch_id_status", "import_batch_id", "status"),
    )

    @classmethod
    def from_domain(cls, domain_obj: DomainImportResult) -> Self:
        """Create a persistence model from a domain ImportResult object."""
        return cls(
            id=domain_obj.id,
            import_batch_id=domain_obj.import_batch_id,
            status=domain_obj.status,
            reference_id=domain_obj.reference_id,
            failure_details=domain_obj.failure_details,
        )

    def to_domain(
        self,
        preload: list[GenericSQLPreloadableType] | None = None,
    ) -> DomainImportResult:
        """Convert the persistence model into an Domain ImportResult object."""
        return DomainImportResult(
            id=self.id,
            import_batch_id=self.import_batch_id,
            status=self.status,
            reference_id=self.reference_id,
            failure_details=self.failure_details,
            import_batch=self.import_batch.to_domain()
            if "import_batch" in (preload or [])
            else None,
        )


class ImportBatch(GenericSQLPersistence[DomainImportBatch]):
    """
    SQL Persistence model for an ImportBatch.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    __tablename__ = "import_batch"

    import_record_id: Mapped[UUID] = mapped_column(
        SQL_UUID, ForeignKey("import_record.id"), nullable=False
    )

    storage_url: Mapped[str] = mapped_column(String, nullable=False)

    import_record: Mapped["ImportRecord"] = relationship(
        "ImportRecord", back_populates="batches"
    )
    import_results: Mapped[list[ImportResult]] = relationship(
        "ImportResult", back_populates="import_batch"
    )

    __table_args__ = (
        UniqueConstraint(
            "import_record_id",
            "storage_url",
            name="uix_import_batch",
        ),
        Index("ix_import_batch_import_record_id", "import_record_id"),
    )

    @classmethod
    def from_domain(cls, domain_obj: DomainImportBatch) -> Self:
        """Create a persistence model from a domain ImportBatch object."""
        return cls(
            id=domain_obj.id,
            import_record_id=domain_obj.import_record_id,
            storage_url=str(domain_obj.storage_url),
        )

    def to_domain(
        self,
        preload: list[GenericSQLPreloadableType] | None = None,
    ) -> DomainImportBatch:
        """Convert the persistence model into an Domain ImportBatch object."""
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            storage_url=HttpUrl(self.storage_url),
            import_record=self.import_record.to_domain()
            if "import_record" in (preload or [])
            else None,
            import_results=[result.to_domain() for result in self.import_results]
            if "import_results" in (preload or [])
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
    notes: Mapped[str | None] = mapped_column(String)
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
    def from_domain(cls, domain_obj: DomainImportRecord) -> Self:
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

    def to_domain(
        self,
        preload: list[GenericSQLPreloadableType] | None = None,
    ) -> DomainImportRecord:
        """Convert the persistence model into an Domain ImportRecord object."""
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
            batches=[batch.to_domain() for batch in self.batches]
            if "batches" in (preload or [])
            else None,
        )
