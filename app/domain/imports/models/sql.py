"""Objects used to interface with SQL implementations."""

import datetime
import uuid
from typing import Self

from pydantic import HttpUrl
from sqlalchemy import (
    UUID,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    case,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.domain.imports.models.models import (
    CollisionStrategy,
    ImportBatchStatus,
    ImportRecordStatus,
    ImportResultStatus,
)
from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.models import (
    ImportResult as DomainImportResult,
)
from app.persistence.sql.persistence import GenericSQLPersistence


class ImportResult(GenericSQLPersistence[DomainImportResult]):
    """SQL model for an individual import result."""

    __tablename__ = "import_result"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("import_batch.id"), nullable=False
    )
    status: Mapped[ImportResultStatus] = mapped_column(
        ENUM(
            *[status.value for status in ImportResultStatus],
            name="import_result_status",
        ),
        nullable=False,
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
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
        preload: list[str] | None = None,
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

    import_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("import_record.id"), nullable=False
    )

    collision_strategy: Mapped[CollisionStrategy] = mapped_column(
        ENUM(
            *[strategy.value for strategy in CollisionStrategy],
            name="collision_strategy",
        ),
        nullable=False,
    )
    storage_url: Mapped[str] = mapped_column(String, nullable=False)

    # Annoying redefinition of id so we can use the class variable in the status join
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    # This looks worse than it is. Importantly, this only scans once so should be good
    # enough (for now?)
    status = column_property(
        select(
            case(
                # No results -> CREATED
                (func.count(ImportResult.id) == 0, ImportBatchStatus.CREATED.value),
                # Has non-terminal statuses -> STARTED
                (
                    func.count(
                        case(
                            (
                                ImportResult.status.in_(
                                    [
                                        ImportResultStatus.CREATED.value,
                                        ImportResultStatus.STARTED.value,
                                        ImportResultStatus.RETRYING.value,
                                    ]
                                ),
                                1,
                            )
                        )
                    )
                    > 0,
                    ImportBatchStatus.STARTED.value,
                ),
                # All failed -> FAILED
                (
                    func.count(ImportResult.id)
                    == func.count(
                        case(
                            (
                                ImportResult.status == ImportResultStatus.FAILED.value,
                                1,
                            )
                        )
                    ),
                    ImportBatchStatus.FAILED.value,
                ),
                # Has failures -> PARTIALLY_FAILED
                (
                    func.count(
                        case(
                            (
                                ImportResult.status.in_(
                                    [
                                        ImportResultStatus.FAILED.value,
                                        ImportResultStatus.PARTIALLY_FAILED.value,
                                    ]
                                ),
                                1,
                            )
                        )
                    )
                    > 0,
                    ImportBatchStatus.PARTIALLY_FAILED.value,
                ),
                # Default -> COMPLETED
                else_=ImportBatchStatus.COMPLETED.value,
            )
        )
        .where(ImportResult.import_batch_id == id)
        .correlate_except(ImportResult)
        .scalar_subquery(),
    )

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
            collision_strategy=domain_obj.collision_strategy,
            storage_url=str(domain_obj.storage_url),
        )

    def to_domain(
        self,
        preload: list[str] | None = None,
    ) -> DomainImportBatch:
        """Convert the persistence model into an Domain ImportBatch object."""
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            collision_strategy=self.collision_strategy,
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
        preload: list[str] | None = None,
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
