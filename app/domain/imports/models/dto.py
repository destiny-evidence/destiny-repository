"""Data transfer objects used to interface between domain and persistence models."""

import asyncio
import datetime
import uuid
from typing import Self

from pydantic import HttpUrl

from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportBatchStatus,
    ImportRecordStatus,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
)
from app.persistence.sql.dto import GenericSQLDTO


class ImportBatchDTO(GenericSQLDTO[DomainImportBatch, SQLImportBatch]):
    """
    Data Transfer Object for an ImportBatch.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    id: uuid.UUID
    import_record_id: uuid.UUID
    status: ImportBatchStatus
    storage_url: str

    import_record: "ImportRecordDTO | None" = None

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportBatch) -> Self:
        """Create a DTO from a domain ImportBatch object."""
        return cls(
            id=domain_obj.id,
            import_record_id=domain_obj.import_record_id,
            status=domain_obj.status,
            storage_url=str(domain_obj.storage_url),
        )

    @classmethod
    async def from_sql(
        cls, sql_obj: SQLImportBatch, preloaded: list[str] | None = None
    ) -> Self:
        """Create a DTO from a SQL ImportBatch object."""
        if not preloaded:
            preloaded = []
        return cls(
            id=sql_obj.id,
            import_record_id=sql_obj.import_record_id,
            status=sql_obj.status,
            storage_url=sql_obj.storage_url,
            preloaded=preloaded,
            import_record=await ImportRecordDTO.from_sql(sql_obj.import_record)
            if "import_record" in preloaded
            else None,
        )

    async def to_sql(self) -> SQLImportBatch:
        """Convert the DTO into an SQL ImportBatch object."""
        return SQLImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=self.storage_url,
        )

    async def to_domain(self) -> DomainImportBatch:
        """Convert the DTO into an Domain ImportBatch object."""
        if (self.import_record is None) == ("import_record" in self.preloaded):
            msg = "Inconsistent state: import_record must be present iff preloaded."
            raise AssertionError(msg)
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=HttpUrl(self.storage_url),
            import_record=await self.import_record.to_domain()  # type: ignore[union-attr]
            if "import_record" in self.preloaded
            else None,
        )


class ImportRecordDTO(GenericSQLDTO[DomainImportRecord, SQLImportRecord]):
    """
    Data Transfer Object for an ImportRecord.

    This is used in the repository layer to pass data between the domain and the
    database.
    """

    id: uuid.UUID
    search_string: str | None
    searched_at: datetime.datetime
    processor_name: str
    processor_version: str
    notes: str | None
    expected_reference_count: int
    source_name: str
    status: ImportRecordStatus

    batches: list[ImportBatchDTO] | None = None

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportRecord) -> Self:
        """Create a DTO from a domain ImportRecord object."""
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

    @classmethod
    async def from_sql(
        cls, sql_obj: SQLImportRecord, preloaded: list[str] | None = None
    ) -> Self:
        """Create a DTO from a SQL ImportRecord object."""
        if not preloaded:
            preloaded = []
        return cls(
            id=sql_obj.id,
            search_string=sql_obj.search_string,
            searched_at=sql_obj.searched_at,
            processor_name=sql_obj.processor_name,
            processor_version=sql_obj.processor_version,
            notes=sql_obj.notes,
            expected_reference_count=sql_obj.expected_reference_count,
            source_name=sql_obj.source_name,
            status=sql_obj.status,
            preloaded=preloaded,
            batches=await asyncio.gather(
                *(ImportBatchDTO.from_sql(batch) for batch in sql_obj.batches)
            )
            if "batches" in preloaded
            else None,
        )

    async def to_sql(self) -> SQLImportRecord:
        """Convert the DTO into an SQL ImportRecord object."""
        return SQLImportRecord(
            id=self.id,
            search_string=self.search_string,
            searched_at=self.searched_at,
            processor_name=self.processor_name,
            processor_version=self.processor_version,
            notes=self.notes,
            expected_reference_count=self.expected_reference_count,
            source_name=self.source_name,
            status=self.status,
        )

    async def to_domain(self) -> DomainImportRecord:
        """Convert the DTO into an Domain ImportRecord object."""
        if (self.batches is None) == ("batches" in self.preloaded):
            msg = "Inconsistent state: batches must be present iff preloaded."
            raise AssertionError(msg)
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
            batches=await asyncio.gather(*(batch.to_domain() for batch in self.batches))  # type: ignore[union-attr]
            if "batches" in self.preloaded
            else None,
        )
