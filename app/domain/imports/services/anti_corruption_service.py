"""Anti-corruption service for imports domain."""

import uuid

import destiny_sdk
from pydantic import ValidationError

from app.core.exceptions import DomainToSDKError, SDKToDomainError
from app.domain.imports.models.models import (
    ImportBatch,
    ImportRecord,
    ImportResult,
    ImportResultStatus,
)
from app.domain.service import GenericAntiCorruptionService


class ImportAntiCorruptionService(GenericAntiCorruptionService):
    """Anti-corruption service for translating between Imports domain and SDK."""

    def __init__(self) -> None:
        """Initialize the anti-corruption service."""
        super().__init__()

    def import_record_to_sdk(
        self, import_record: ImportRecord
    ) -> destiny_sdk.imports.ImportRecordRead:
        """Convert the ImportRecord to an SDK model."""
        try:
            return destiny_sdk.imports.ImportRecordRead.model_validate(
                import_record.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def import_record_from_sdk(
        self, import_in: destiny_sdk.imports.ImportRecordIn
    ) -> ImportRecord:
        """Create an ImportRecord from the SDK input model."""
        try:
            import_record = ImportRecord.model_validate(import_in.model_dump())
            import_record.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return import_record

    def import_batch_to_sdk(
        self, import_batch: ImportBatch
    ) -> destiny_sdk.imports.ImportBatchRead:
        """Convert the ImportBatch to an SDK model."""
        try:
            return destiny_sdk.imports.ImportBatchRead.model_validate(
                import_batch.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception

    def import_batch_to_sdk_summary(
        self, import_batch: ImportBatch
    ) -> destiny_sdk.imports.ImportBatchSummary:
        """Convert the ImportBatch to an SDK summary model."""
        try:
            result_summary: dict[ImportResultStatus, int] = dict.fromkeys(
                ImportResultStatus, 0
            )
            failure_details: list[str] = []
            for result in import_batch.import_results or []:
                result_summary[result.status] += 1
                if (
                    result.status
                    in (
                        ImportResultStatus.FAILED,
                        ImportResultStatus.PARTIALLY_FAILED,
                    )
                    and result.failure_details
                ):
                    failure_details.append(result.failure_details)
            return destiny_sdk.imports.ImportBatchSummary.model_validate(
                import_batch.model_dump()
                | {
                    "import_batch_id": import_batch.id,
                    "import_batch_status": import_batch.status,
                    "results": result_summary,
                    "failure_details": failure_details,
                }
            )
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception

    def import_batch_from_sdk(
        self,
        import_batch_in: destiny_sdk.imports.ImportBatchIn,
        import_record_id: uuid.UUID,
    ) -> ImportBatch:
        """Create an ImportBatch from the SDK input model."""
        try:
            import_batch = ImportBatch.model_validate(
                import_batch_in.model_dump() | {"import_record_id": import_record_id}
            )
            import_batch.check_serializability()
        except ValidationError as exception:
            raise SDKToDomainError(errors=exception.errors()) from exception
        else:
            return import_batch

    def import_result_to_sdk(
        self, import_result: ImportResult
    ) -> destiny_sdk.imports.ImportResultRead:
        """Convert the ImportResult to an SDK model."""
        try:
            return destiny_sdk.imports.ImportResultRead.model_validate(
                import_result.model_dump()
            )
        except ValidationError as exception:
            raise DomainToSDKError(errors=exception.errors()) from exception
