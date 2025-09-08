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
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.exceptions import SQLSelectionError
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
    callback_url: Mapped[str | None] = mapped_column(String, nullable=True)

    @hybrid_property
    def status(self) -> ImportBatchStatus:
        """Calculate status from loaded import_results relationship."""
        # A note to the future: this would be more performant using
        # @status.inplace.expression to perform the calculation in the SQL layer.
        # If we get to the point where performance is a concern, we can revisit.
        # I (Adam) tried really hard, but couldn't land it. Here's where I got:
        # - You must specify the hybrid column explicitly in every relevant query
        # - You must then hydrate the column into the domain model manually
        # - (SQLAlchemy + async is the main demon here, forcing us to get everything
        #    at query time)
        # - That is okay with some low-level surgery, but the real pain comes
        #   in handling that with relationships, eg hydrating import_batches on an
        #   import record. It's solvable but didn't seem worth the massive amount of
        #   complexity it caused in the repository layer.
        # There are other valid approaches too!

        # As it is, this uses the selectin lazy load on the relationship. The preloaded
        # import_results are then discarded in the domain transition unless explicitly
        # requested in the repo's preload arguments, so memory pressure is transient.
        # Now let me close my eyes and manifest that the simplicity of this approach is
        # worth it.
        if self.import_results is None:
            msg = "ImportBatch.status requires import_results to be preloaded."
            raise SQLSelectionError(msg)

        statuses = {result.status for result in self.import_results}
        if not statuses or statuses == {ImportResultStatus.CREATED}:
            return ImportBatchStatus.CREATED

        non_terminal_statuses = {
            ImportResultStatus.STARTED,
            ImportResultStatus.RETRYING,
            ImportResultStatus.CREATED,
        }
        success_statuses = {
            ImportResultStatus.COMPLETED,
            ImportResultStatus.PARTIALLY_FAILED,
        }

        if non_terminal_statuses.intersection(statuses):
            return ImportBatchStatus.STARTED

        if ImportResultStatus.FAILED in statuses:
            if success_statuses.intersection(statuses):
                return ImportBatchStatus.PARTIALLY_FAILED
            return ImportBatchStatus.FAILED

        return ImportBatchStatus.COMPLETED

    import_record: Mapped["ImportRecord"] = relationship(
        "ImportRecord", back_populates="batches"
    )
    import_results: Mapped[list["ImportResult"]] = relationship(
        "ImportResult", back_populates="import_batch", lazy="selectin"
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
            callback_url=str(domain_obj.callback_url)
            if domain_obj.callback_url
            else None,
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
            callback_url=HttpUrl(self.callback_url) if self.callback_url else None,
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

    import_batch: Mapped[ImportBatch] = relationship(
        "ImportBatch", back_populates="import_results"
    )

    __table_args__ = (Index("ix_import_result_import_batch_id", "import_batch_id"),)

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
