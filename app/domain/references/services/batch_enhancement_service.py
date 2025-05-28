"""Service for managing batch enhancements."""

from io import BytesIO

import destiny_sdk

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
)
from app.domain.references.models.validators import (
    BatchEnhancementResultValidator,
)
from app.domain.service import GenericService
from app.persistence.blob.models import (
    BlobStorageFile,
)
from app.persistence.blob.service import (
    get_file_from_blob_storage,
    get_signed_url,
    upload_file_to_blob_storage,
)
from app.persistence.blob.stream import FileStream
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger()
settings = get_settings()


class BatchEnhancementService(GenericService):
    """Service for managing batch enhancements."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    async def build_robot_request(
        self,
        file_stream: FileStream,
        batch_enhancement_request: BatchEnhancementRequest,
    ) -> destiny_sdk.robots.BatchRobotRequest:
        """Build a robot request from a batch enhancement request."""
        # Build jsonl file data using SDK model
        file = await upload_file_to_blob_storage(
            content=file_stream,
            path="batch_enhancement_request_reference_data",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        batch_enhancement_request.reference_data_file = file
        batch_enhancement_request.result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="batch_enhancement_result",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        batch_enhancement_request = await self.sql_uow.batch_enhancement_requests.update_by_pk(  # noqa: E501
            batch_enhancement_request.id,
            reference_data_file=batch_enhancement_request.reference_data_file.to_sql(),
            result_file=batch_enhancement_request.result_file.to_sql(),
        )

        return batch_enhancement_request.to_batch_robot_request_sdk(get_signed_url)

    async def validate_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
    ) -> BatchEnhancementResultValidator:
        """Validate the result of a batch enhancement request."""
        if not batch_enhancement_request.result_file:
            msg = (
                "Batch enhancement request has no result file location. This should "
                "not happen."
            )
            raise RuntimeError(msg)
        content = await get_file_from_blob_storage(
            batch_enhancement_request.result_file
        )
        json_content = content.decode("utf-8").split("\n")

        return BatchEnhancementResultValidator.from_raw(
            json_content, set(batch_enhancement_request.reference_ids)
        )

    async def finalise_and_store_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        batch_enhancement_result: BatchEnhancementResultValidator,
        successes: list[str],
        import_failures: list[str],
    ) -> tuple[BatchEnhancementRequestStatus, BlobStorageFile]:
        """Post import validation of batch enhancement result."""
        if missing_references := (
            set(batch_enhancement_request.reference_ids)
            - batch_enhancement_result.reference_ids
        ):
            import_failures.extend(
                f"Reference {missing_reference}: not in batch enhancement result from "
                "robot."
                for missing_reference in missing_references
            )

        failures = (
            batch_enhancement_result.parse_failures
            + [error.message for error in batch_enhancement_result.robot_errors]
            + import_failures
        )

        if failures and successes:
            status = BatchEnhancementRequestStatus.PARTIAL_FAILED
        elif not successes:
            status = BatchEnhancementRequestStatus.FAILED
        else:
            status = BatchEnhancementRequestStatus.COMPLETED

        validation_result_file_content = "\n".join([*successes, *failures]).encode(
            "utf-8"
        )
        # No streaming for validation result file for now due to side-effects of the
        # theoretical generator's results (success/failure metrics needed other than
        # the file). Streaming may require saving of each entry's result to SQL and
        # reading using FileStream.
        validation_result_file = await upload_file_to_blob_storage(
            content=BytesIO(validation_result_file_content),
            path="batch_enhancement_result",
            filename=f"{batch_enhancement_request.id}.txt",
        )

        return status, validation_result_file
