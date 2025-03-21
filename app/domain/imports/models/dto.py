"""Data transfer objects used to interface between domain and persistence models."""

import asyncio
import datetime
import uuid
from typing import Optional, Self

from pydantic import HttpUrl, ValidationError

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
    import_record: Optional["ImportRecordDTO"]

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportBatch) -> Self:
        """Create a DTO from a domain ImportBatch object."""
        return cls(
            id=domain_obj.id,
            import_record_id=domain_obj.import_record_id,
            status=domain_obj.status,
            storage_url=str(domain_obj.storage_url),
            import_record=await ImportRecordDTO.from_domain(domain_obj.import_record)
            if domain_obj.import_record
            else None,
        )

    @classmethod
    async def from_sql(cls, sql_obj: SQLImportBatch) -> Self:
        """Create a DTO from a SQL ImportBatch object."""
        return cls(
            id=sql_obj.id,
            import_record_id=sql_obj.import_record_id,
            status=sql_obj.status,
            storage_url=sql_obj.storage_url,
            import_record=await ImportRecordDTO.from_sql(sql_obj.import_record)
            if sql_obj.import_record
            else None,
        )

    async def to_sql(self) -> SQLImportBatch:
        """Convert the DTO into an SQL ImportBatch object."""
        return SQLImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=self.storage_url,
            import_record=await self.import_record.to_sql()
            if self.import_record
            else None,
        )

    async def to_domain(self) -> DomainImportBatch:
        """Convert the DTO into an Domain ImportBatch object."""
        if not self.import_record:
            msg = "ImportRecord must be set to convert to domain."
            raise ValidationError(msg)
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=HttpUrl(self.storage_url),
            import_record=await self.import_record.to_domain(),
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
    batches: list[ImportBatchDTO]

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
            batches=await asyncio.gather(
                *(ImportBatchDTO.from_domain(batch) for batch in domain_obj.batches)
            ),
        )

    @classmethod
    async def from_sql(cls, sql_obj: SQLImportRecord) -> Self:
        """Create a DTO from a SQL ImportRecord object."""
        return cls(
            id=sql_obj.id,
            search_string=sql_obj.search_string,
            searched_at=sql_obj.searched_at,
            processor_name=sql_obj.processor_name,
            processor_version=sql_obj.processor_version,
            notes=sql_obj.notes,
            expected_reference_count=sql_obj.expected_reference_count,
            source_name=sql_obj.source_name,
            status=ImportRecordStatus[sql_obj.status],
            batches=await asyncio.gather(
                *(ImportBatchDTO.from_sql(batch) for batch in sql_obj.batches)
            ),
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
            batches=await asyncio.gather(*(batch.to_sql() for batch in self.batches)),
        )

    async def to_domain(self) -> DomainImportRecord:
        """Convert the DTO into an Domain ImportRecord object."""
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
            batches=await asyncio.gather(
                *(batch.to_domain() for batch in self.batches)
            ),
        )
