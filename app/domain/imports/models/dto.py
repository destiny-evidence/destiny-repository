"""Data transfer objects used to interface between domain and persistence models."""

import asyncio
import datetime
import uuid
from typing import Optional, Self

from pydantic import HttpUrl

from app.domain.imports.models.models import (
    ImportBatch as DomainImportBatch,
)
from app.domain.imports.models.models import (
    ImportRecord as DomainImportRecord,
)
from app.domain.imports.models.models import (
    ImportResult as DomainImportResult,
)
from app.domain.imports.models.sql import (
    ImportBatch as SQLImportBatch,
)
from app.domain.imports.models.sql import (
    ImportBatchStatus,
    ImportRecordStatus,
    ImportResultStatus,
)
from app.domain.imports.models.sql import (
    ImportRecord as SQLImportRecord,
)
from app.domain.imports.models.sql import (
    ImportResult as SQLImportResult,
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
    created_at: datetime.datetime
    updated_at: datetime.datetime

    import_record: Optional["ImportRecordDTO"] = None
    import_results: list["ImportResultDTO"] | None = None

    @property
    def _possible_preloads(self) -> list[str]:
        """A list of attributes that can be preloaded from the SQL layer."""
        return ["import_record", "import_results"]

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportBatch) -> Self:
        """Create a DTO from a domain ImportBatch object."""
        return cls(
            id=domain_obj.id,
            import_record_id=domain_obj.import_record_id,
            status=domain_obj.status,
            storage_url=str(domain_obj.storage_url),
            created_at=domain_obj.created_at,
            updated_at=domain_obj.updated_at,
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
            preloaded=preloaded if preloaded else [],
            created_at=sql_obj.created_at,
            updated_at=sql_obj.updated_at,
            import_record=await ImportRecordDTO.from_sql(sql_obj.import_record)
            if "import_record" in preloaded
            else None,
            import_results=await asyncio.gather(
                *(ImportResultDTO.from_sql(result) for result in sql_obj.import_results)
            )
            if "import_results" in preloaded
            else None,
        )

    async def to_sql(self) -> SQLImportBatch:
        """Convert the DTO into an SQL ImportBatch object."""
        return SQLImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=self.storage_url,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    async def to_domain(self) -> DomainImportBatch:
        """Convert the DTO into an Domain ImportBatch object."""
        self._validate_preloads()
        return DomainImportBatch(
            id=self.id,
            import_record_id=self.import_record_id,
            status=self.status,
            storage_url=HttpUrl(self.storage_url),
            created_at=self.created_at,
            updated_at=self.updated_at,
            import_record=await self.import_record.to_domain()  # type: ignore[union-attr]
            if "import_record" in self.preloaded
            else None,
            import_results=await asyncio.gather(
                *(result.to_domain() for result in self.import_results)  # type: ignore[union-attr]
            )
            if "import_results" in self.preloaded
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
    created_at: datetime.datetime
    updated_at: datetime.datetime

    batches: list[ImportBatchDTO] | None = None

    @property
    def _possible_preloads(self) -> list[str]:
        """A list of attributes that can be preloaded from the SQL layer."""
        return ["batches"]

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
            created_at=domain_obj.created_at,
            updated_at=domain_obj.updated_at,
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
            created_at=sql_obj.created_at,
            updated_at=sql_obj.updated_at,
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
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    async def to_domain(self) -> DomainImportRecord:
        """Convert the DTO into an Domain ImportRecord object."""
        self._validate_preloads()
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
            created_at=self.created_at,
            updated_at=self.updated_at,
            batches=await asyncio.gather(*(batch.to_domain() for batch in self.batches))  # type: ignore[union-attr]
            if "batches" in self.preloaded
            else None,
        )


class ImportResultDTO(GenericSQLDTO[DomainImportResult, SQLImportResult]):
    """Data Transfer Object for an ImportResult."""

    id: uuid.UUID
    import_batch_id: uuid.UUID
    failure_details: str | None
    status: ImportResultStatus
    reference_id: uuid.UUID | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    import_batch: ImportBatchDTO | None = None

    @property
    def _possible_preloads(self) -> list[str]:
        """A list of attributes that can be preloaded from the SQL layer."""
        return ["import_batch"]

    @classmethod
    async def from_domain(cls, domain_obj: DomainImportResult) -> Self:
        """Create a DTO from a domain ImportResult object."""
        return cls(
            id=domain_obj.id,
            import_batch_id=domain_obj.import_batch_id,
            failure_details=domain_obj.failure_details,
            status=domain_obj.status,
            reference_id=domain_obj.reference_id,
            created_at=domain_obj.created_at,
            updated_at=domain_obj.updated_at,
        )

    @classmethod
    async def from_sql(
        cls, sql_obj: SQLImportResult, preloaded: list[str] | None = None
    ) -> Self:
        """Create a DTO from a SQL ImportResult object."""
        if not preloaded:
            preloaded = []
        return cls(
            id=sql_obj.id,
            import_batch_id=sql_obj.import_batch_id,
            failure_details=sql_obj.failure_details,
            status=sql_obj.status,
            reference_id=sql_obj.reference_id,
            created_at=sql_obj.created_at,
            updated_at=sql_obj.updated_at,
        )

    async def to_sql(self) -> SQLImportResult:
        """Convert the DTO into an SQL ImportResult object."""
        return SQLImportResult(
            id=self.id,
            import_batch_id=self.import_batch_id,
            failure_details=self.failure_details,
            status=self.status,
            reference_id=self.reference_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    async def to_domain(self) -> DomainImportResult:
        """Convert the DTO into an Domain ImportResult object."""
        self._validate_preloads()
        return DomainImportResult(
            id=self.id,
            import_batch_id=self.import_batch_id,
            failure_details=self.failure_details,
            status=self.status,
            reference_id=self.reference_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            import_batch=await self.import_batch.to_domain()  # type: ignore[union-attr]
            if "import_batch" in self.preloaded
            else None,
        )
