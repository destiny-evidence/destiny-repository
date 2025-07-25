"""Service for managing batch enhancements."""

from collections.abc import AsyncGenerator, Awaitable, Callable

import destiny_sdk
from pydantic import UUID4

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    BatchRobotResultValidationEntry,
    Enhancement,
)
from app.domain.references.models.validators import (
    BatchEnhancementResultValidator,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.blob.models import (
    BlobStorageFile,
)
from app.persistence.blob.repository import BlobRepository
from app.persistence.blob.stream import FileStream
from app.persistence.sql.uow import AsyncSqlUnitOfWork

logger = get_logger()
settings = get_settings()


class BatchEnhancementService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing batch enhancements."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def mark_batch_enhancement_request_failed(
        self, batch_enhancement_request_id: UUID4, error: str
    ) -> BatchEnhancementRequest:
        """Mark a batch enhancement request as failed and supply error message."""
        return await self.sql_uow.batch_enhancement_requests.update_by_pk(
            pk=batch_enhancement_request_id,
            request_status=BatchEnhancementRequestStatus.FAILED,
            error=error,
        )

    async def update_batch_enhancement_request_status(
        self,
        batch_enhancement_request_id: UUID4,
        status: BatchEnhancementRequestStatus,
    ) -> BatchEnhancementRequest:
        """Update a batch enhancement request."""
        return await self.sql_uow.batch_enhancement_requests.update_by_pk(
            pk=batch_enhancement_request_id, request_status=status
        )

    async def add_validation_result_file_to_batch_enhancement_request(
        self,
        batch_enhancement_request_id: UUID4,
        validation_result_file: BlobStorageFile,
    ) -> BatchEnhancementRequest:
        """Add a validation result file to a batch enhancement request."""
        return await self.sql_uow.batch_enhancement_requests.update_by_pk(
            pk=batch_enhancement_request_id,
            validation_result_file=validation_result_file.to_sql(),
        )

    async def build_robot_request(
        self,
        blob_repository: BlobRepository,
        file_stream: FileStream,
        batch_enhancement_request: BatchEnhancementRequest,
    ) -> destiny_sdk.robots.BatchRobotRequest:
        """Build a robot request from a batch enhancement request."""
        # Build jsonl file data using SDK model
        file = await blob_repository.upload_file_to_blob_storage(
            content=file_stream,
            path="batch_enhancement_request_reference_data",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        batch_enhancement_request.reference_data_file = file
        batch_enhancement_request.result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="batch_enhancement_result",
            filename=f"{batch_enhancement_request.id}_robot.jsonl",
        )

        batch_enhancement_request = await self.sql_uow.batch_enhancement_requests.update_by_pk(  # noqa: E501
            batch_enhancement_request.id,
            reference_data_file=batch_enhancement_request.reference_data_file.to_sql(),
            result_file=batch_enhancement_request.result_file.to_sql(),
        )

        return (
            await self._anti_corruption_service.batch_enhancement_request_to_sdk_robot(
                batch_enhancement_request
            )
        )

    async def process_batch_enhancement_result(
        self,
        blob_repository: BlobRepository,
        batch_enhancement_request: BatchEnhancementRequest,
        add_enhancement: Callable[[Enhancement], Awaitable[tuple[bool, str]]],
        # Mutable argument to give caller visibility of imported enhancements
        imported_enhancement_ids: set[UUID4],
    ) -> AsyncGenerator[str, None]:
        """
        Validate the result of a batch enhancement request.

        This generator yields validation messages which are streamed into the
        result file of the batch enhancement request.
        """
        if not batch_enhancement_request.result_file:
            msg = (
                "Batch enhancement request has no result file. "
                "This should not happen."
            )
            raise RuntimeError(msg)
        expected_reference_ids = set(batch_enhancement_request.reference_ids)
        at_least_one_failed = False
        at_least_one_succeeded = False
        attempted_reference_ids: set[UUID4] = set()
        async with blob_repository.stream_file_from_blob_storage(
            batch_enhancement_request.result_file,
        ) as file_stream:
            # Read the file stream and validate the content
            line_no = 1
            async for line in file_stream:
                if not line.strip():
                    continue
                validated_result = await BatchEnhancementResultValidator.from_raw(
                    line, line_no, expected_reference_ids
                )
                line_no += 1
                if validated_result.robot_error:
                    attempted_reference_ids.add(
                        validated_result.robot_error.reference_id
                    )
                    at_least_one_failed = True
                    yield self._anti_corruption_service.batch_robot_result_validation_entry_to_sdk(  # noqa: E501
                        BatchRobotResultValidationEntry(
                            reference_id=validated_result.robot_error.reference_id,
                            error=validated_result.robot_error.message,
                        )
                    ).to_jsonl()
                elif validated_result.parse_failure:
                    at_least_one_failed = True
                    yield self._anti_corruption_service.batch_robot_result_validation_entry_to_sdk(  # noqa: E501
                        BatchRobotResultValidationEntry(
                            error=validated_result.parse_failure,
                        )
                    ).to_jsonl()
                elif validated_result.enhancement_to_add:
                    attempted_reference_ids.add(
                        validated_result.enhancement_to_add.reference_id
                    )
                    # NB this generates the UUID that we import into the database,
                    # which is handy!
                    enhancement = self._anti_corruption_service.enhancement_from_sdk(
                        validated_result.enhancement_to_add
                    )
                    success, message = await add_enhancement(enhancement)
                    if success:
                        yield self._anti_corruption_service.batch_robot_result_validation_entry_to_sdk(  # noqa: E501
                            BatchRobotResultValidationEntry(
                                reference_id=validated_result.enhancement_to_add.reference_id,
                            )
                        ).to_jsonl()
                        imported_enhancement_ids.add(enhancement.id)
                        at_least_one_succeeded = True
                    else:
                        yield self._anti_corruption_service.batch_robot_result_validation_entry_to_sdk(  # noqa: E501
                            BatchRobotResultValidationEntry(
                                reference_id=validated_result.enhancement_to_add.reference_id,
                                error=message,
                            )
                        ).to_jsonl()
                        at_least_one_failed = True

        if missing_reference_ids := (expected_reference_ids - attempted_reference_ids):
            for missing_reference_id in missing_reference_ids:
                at_least_one_failed = True
                yield self._anti_corruption_service.batch_robot_result_validation_entry_to_sdk(  # noqa: E501
                    BatchRobotResultValidationEntry(
                        reference_id=missing_reference_id,
                        error="Requested reference not in batch enhancement result.",
                    )
                ).to_jsonl()

        await self.finalize_batch_enhancement_request(
            batch_enhancement_request,
            at_least_one_failed=at_least_one_failed,
            at_least_one_succeeded=at_least_one_succeeded,
        )

    async def finalize_batch_enhancement_request(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        *,
        at_least_one_failed: bool,
        at_least_one_succeeded: bool,
    ) -> None:
        """Finalize the batch enhancement request."""
        if at_least_one_failed and at_least_one_succeeded:
            await self.update_batch_enhancement_request_status(
                batch_enhancement_request.id,
                BatchEnhancementRequestStatus.PARTIAL_FAILED,
            )
        elif not at_least_one_succeeded:
            await self.mark_batch_enhancement_request_failed(
                batch_enhancement_request.id,
                "Result received but every enhancement failed.",
            )
        else:
            await self.update_batch_enhancement_request_status(
                batch_enhancement_request.id, BatchEnhancementRequestStatus.COMPLETED
            )
