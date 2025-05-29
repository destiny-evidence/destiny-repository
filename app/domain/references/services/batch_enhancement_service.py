"""Service for managing batch enhancements."""

from collections.abc import AsyncGenerator, Awaitable, Callable

import destiny_sdk
from pydantic import UUID4

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Enhancement,
)
from app.domain.references.models.validators import (
    BatchEnhancementResultValidator,
)
from app.domain.service import GenericService
from app.persistence.blob.models import (
    BlobStorageFile,
)
from app.persistence.blob.service import (
    get_signed_url,
    stream_file_from_blob_storage,
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
            validation_result_file=await validation_result_file.to_sql(),
        )

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
            reference_data_file=await batch_enhancement_request.reference_data_file.to_sql(),  # noqa: E501
            result_file=await batch_enhancement_request.result_file.to_sql(),
        )

        return await batch_enhancement_request.to_batch_robot_request_sdk(
            get_signed_url
        )

    async def process_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        add_enhancement: Callable[[Enhancement], Awaitable[tuple[bool, str]]],
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
        successes: list[str] = []
        failures: list[str] = []
        attempted_reference_ids: set[UUID4] = set()
        async with stream_file_from_blob_storage(
            batch_enhancement_request.result_file,
        ) as file_stream:
            # Read the file stream and validate the content
            i = 1
            async for line in file_stream:
                if not line.strip():
                    continue
                validated_result = await BatchEnhancementResultValidator.from_raw(
                    line, i, expected_reference_ids
                )
                i += 1
                if validated_result.robot_error:
                    failures.append(validated_result.robot_error.message)
                    yield validated_result.robot_error.message
                elif validated_result.parse_failure:
                    failures.append(validated_result.parse_failure)
                    yield validated_result.parse_failure
                elif validated_result.enhancement_to_add:
                    attempted_reference_ids.add(
                        validated_result.enhancement_to_add.reference_id
                    )
                    success, message = await add_enhancement(
                        await Enhancement.from_sdk(validated_result.enhancement_to_add)
                    )
                    if success:
                        successes.append(message)
                    else:
                        failures.append(message)
                    yield message

        if missing_reference_ids := (expected_reference_ids - attempted_reference_ids):
            for missing_reference_id in missing_reference_ids:
                msg = (
                    f"Reference {missing_reference_id}: not in batch enhancement "
                    "result from robot."
                )
                failures.append(msg)
                yield msg

        await self.finalize_batch_enhancement_request(
            batch_enhancement_request,
            failures=failures,
            successes=successes,
        )

    async def finalize_batch_enhancement_request(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        failures: list[str],
        successes: list[str],
    ) -> None:
        """Finalize the batch enhancement request."""
        if failures and successes:
            await self.update_batch_enhancement_request_status(
                batch_enhancement_request.id,
                BatchEnhancementRequestStatus.PARTIAL_FAILED,
            )
        elif not successes:
            await self.mark_batch_enhancement_request_failed(
                batch_enhancement_request.id,
                "Result received but every enhancement failed.",
            )
        else:
            await self.update_batch_enhancement_request_status(
                batch_enhancement_request.id, BatchEnhancementRequestStatus.COMPLETED
            )
