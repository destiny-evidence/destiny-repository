"""Service for managing batch enhancements."""

from collections.abc import AsyncGenerator, Awaitable, Callable

import destiny_sdk
from opentelemetry import trace
from pydantic import UUID4

from app.core.config import get_settings
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    RobotEnhancementBatch,
    RobotResultValidationEntry,
)
from app.domain.references.models.validators import (
    EnhancementResultValidator,
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

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)


class EnhancementService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing batch enhancements."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def mark_enhancement_request_failed(
        self, enhancement_request_id: UUID4, error: str
    ) -> EnhancementRequest:
        """Mark a enhancement request as failed and supply error message."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id,
            request_status=EnhancementRequestStatus.FAILED,
            error=error,
        )

    async def update_enhancement_request_status(
        self,
        enhancement_request_id: UUID4,
        status: EnhancementRequestStatus,
    ) -> EnhancementRequest:
        """Update a enhancement request."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id, request_status=status
        )

    async def build_robot_enhancement_batch(
        self,
        robot_enhancement_batch: RobotEnhancementBatch,
        file_stream: FileStream,
        blob_repository: BlobRepository,
    ) -> RobotEnhancementBatch:
        """
        Create a robot enhancement batch.

        Args:
            robot_enhancement_batch (RobotEnhancementBatch): The robot enhancement
                object.
            file_stream (FileStream): The file stream of references.
            blob_repository (BlobRepository): The blob repository.

        Returns:
            RobotEnhancementBatch: The created robot enhancement batch.

        """
        reference_file = await blob_repository.upload_file_to_blob_storage(
            content=file_stream,
            path="robot_enhancement_batch_reference_data",
            filename=f"{robot_enhancement_batch.id}.jsonl",
        )

        result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="robot_enhancement_batch_result_data",
            filename=f"{robot_enhancement_batch.id}_robot.jsonl",
        )

        return await self.sql_uow.robot_enhancement_batches.update_by_pk(
            pk=robot_enhancement_batch.id,
            reference_file=reference_file.to_sql(),
            result_file=result_file.to_sql(),
        )

    async def add_validation_result_file_to_enhancement_request(
        self,
        enhancement_request_id: UUID4,
        validation_result_file: BlobStorageFile,
    ) -> EnhancementRequest:
        """Add a validation result file to a enhancement request."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id,
            validation_result_file=validation_result_file.to_sql(),
        )

    async def build_robot_request(
        self,
        blob_repository: BlobRepository,
        file_stream: FileStream,
        enhancement_request: EnhancementRequest,
    ) -> destiny_sdk.robots.RobotRequest:
        """Build a robot request from a enhancement request."""
        # Build jsonl file data using SDK model
        file = await blob_repository.upload_file_to_blob_storage(
            content=file_stream,
            path="enhancement_request_reference_data",
            filename=f"{enhancement_request.id}.jsonl",
        )

        enhancement_request.reference_data_file = file
        enhancement_request.result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="enhancement_result",
            filename=f"{enhancement_request.id}_robot.jsonl",
        )

        enhancement_request = await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id,
            reference_data_file=enhancement_request.reference_data_file.to_sql(),
            result_file=enhancement_request.result_file.to_sql(),
        )

        return await self._anti_corruption_service.enhancement_request_to_sdk_robot(
            enhancement_request
        )

    async def process_enhancement_result(
        self,
        blob_repository: BlobRepository,
        enhancement_request: EnhancementRequest,
        add_enhancement: Callable[[Enhancement], Awaitable[tuple[bool, str]]],
        # Mutable argument to give caller visibility of imported enhancements
        imported_enhancement_ids: set[UUID4],
    ) -> AsyncGenerator[str, None]:
        """
        Validate the result of a batch enhancement request.

        This generator yields validation messages which are streamed into the
        result file of the batch enhancement request.
        """
        if not enhancement_request.result_file:
            msg = (
                "Batch enhancement request has no result file. "
                "This should not happen."
            )
            raise RuntimeError(msg)
        expected_reference_ids = set(enhancement_request.reference_ids)
        at_least_one_failed = False
        at_least_one_succeeded = False
        attempted_reference_ids: set[UUID4] = set()
        async with blob_repository.stream_file_from_blob_storage(
            enhancement_request.result_file,
        ) as file_stream:
            # Read the file stream and validate the content
            line_no = 1
            async for line in file_stream:
                with tracer.start_as_current_span(
                    "Import enhancement",
                    attributes={Attributes.FILE_LINE_NO: line_no},
                ):
                    if not line.strip():
                        continue
                    validated_result = await EnhancementResultValidator.from_raw(
                        line, line_no, expected_reference_ids
                    )
                    line_no += 1
                    if validated_result.robot_error:
                        trace_attribute(
                            Attributes.REFERENCE_ID,
                            str(validated_result.robot_error.reference_id),
                        )
                        attempted_reference_ids.add(
                            validated_result.robot_error.reference_id
                        )
                        at_least_one_failed = True
                        yield self._anti_corruption_service.robot_result_validation_entry_to_sdk(  # noqa: E501
                            RobotResultValidationEntry(
                                reference_id=validated_result.robot_error.reference_id,
                                error=validated_result.robot_error.message,
                            )
                        ).to_jsonl()
                    elif validated_result.parse_failure:
                        logger.warning(
                            "Failed to parse enhancement",
                            line_no=line_no,
                            error=validated_result.parse_failure,
                        )
                        at_least_one_failed = True
                        yield self._anti_corruption_service.robot_result_validation_entry_to_sdk(  # noqa: E501
                            RobotResultValidationEntry(
                                error=validated_result.parse_failure,
                            )
                        ).to_jsonl()
                    elif validated_result.enhancement_to_add:
                        trace_attribute(
                            Attributes.REFERENCE_ID,
                            str(validated_result.enhancement_to_add.reference_id),
                        )
                        attempted_reference_ids.add(
                            validated_result.enhancement_to_add.reference_id
                        )
                        # NB this generates the UUID that we import into the database,
                        # which is handy!
                        enhancement = (
                            self._anti_corruption_service.enhancement_from_sdk(
                                validated_result.enhancement_to_add
                            )
                        )
                        trace_attribute(Attributes.ENHANCEMENT_ID, str(enhancement.id))
                        success, message = await add_enhancement(enhancement)
                        if success:
                            yield self._anti_corruption_service.robot_result_validation_entry_to_sdk(  # noqa: E501
                                RobotResultValidationEntry(
                                    reference_id=validated_result.enhancement_to_add.reference_id,
                                )
                            ).to_jsonl()
                            imported_enhancement_ids.add(enhancement.id)
                            at_least_one_succeeded = True
                        else:
                            logger.warning(
                                "Failed to add enhancement",
                                error=message,
                                line_no=line_no,
                                reference_id=enhancement.reference_id,
                                enhancement_id=enhancement.id,
                            )
                            yield self._anti_corruption_service.robot_result_validation_entry_to_sdk(  # noqa: E501
                                RobotResultValidationEntry(
                                    reference_id=validated_result.enhancement_to_add.reference_id,
                                    error=message,
                                )
                            ).to_jsonl()
                            at_least_one_failed = True

        if missing_reference_ids := (expected_reference_ids - attempted_reference_ids):
            for missing_reference_id in missing_reference_ids:
                at_least_one_failed = True
                yield self._anti_corruption_service.robot_result_validation_entry_to_sdk(  # noqa: E501
                    RobotResultValidationEntry(
                        reference_id=missing_reference_id,
                        error="Requested reference not in enhancement result.",
                    )
                ).to_jsonl()

        await self.finalize_enhancement_request(
            enhancement_request,
            at_least_one_failed=at_least_one_failed,
            at_least_one_succeeded=at_least_one_succeeded,
        )

    async def finalize_enhancement_request(
        self,
        enhancement_request: EnhancementRequest,
        *,
        at_least_one_failed: bool,
        at_least_one_succeeded: bool,
    ) -> None:
        """Finalize the enhancement request."""
        if at_least_one_failed and at_least_one_succeeded:
            await self.update_enhancement_request_status(
                enhancement_request.id,
                EnhancementRequestStatus.PARTIAL_FAILED,
            )
        elif not at_least_one_succeeded:
            await self.mark_enhancement_request_failed(
                enhancement_request.id,
                "Result received but every enhancement failed.",
            )
        else:
            await self.update_enhancement_request_status(
                enhancement_request.id, EnhancementRequestStatus.COMPLETED
            )
