"""Service for managing batch enhancements."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import NamedTuple
from uuid import UUID

import destiny_sdk
from opentelemetry import trace

from app.core.config import get_settings
from app.core.telemetry.attributes import Attributes, trace_attribute
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    PendingEnhancement,
    PendingEnhancementStatus,
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


class ProcessedResults(NamedTuple):
    """Results from processing robot enhancement batch."""

    imported_enhancement_ids: set[UUID]
    successful_pending_enhancement_ids: set[UUID]
    failed_pending_enhancement_ids: set[UUID]
    discarded_pending_enhancement_ids: set[UUID]


class EnhancementService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing batch enhancements."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow)

    async def mark_robot_enhancement_batch_failed(
        self, robot_enhancement_batch_id: UUID, error: str
    ) -> RobotEnhancementBatch:
        """Mark a robot enhancement batch as failed and supply error message."""
        await self.update_pending_enhancements_status_for_robot_enhancement_batch(
            robot_enhancement_batch_id,
            PendingEnhancementStatus.FAILED,
        )

        return await self.sql_uow.robot_enhancement_batches.update_by_pk(
            pk=robot_enhancement_batch_id,
            error=error,
        )

    async def update_enhancement_request_status(
        self,
        enhancement_request_id: UUID,
        status: EnhancementRequestStatus,
    ) -> EnhancementRequest:
        """Update a enhancement request."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id, request_status=status
        )

    async def update_pending_enhancements_status(
        self,
        pending_enhancement_ids: list[UUID],
        status: PendingEnhancementStatus,
    ) -> int:
        """Update multiple pending enhancements."""
        return await self.sql_uow.pending_enhancements.bulk_update(
            pks=pending_enhancement_ids, status=status
        )

    async def update_pending_enhancements_status_for_robot_enhancement_batch(
        self,
        robot_enhancement_batch_id: UUID,
        status: PendingEnhancementStatus,
    ) -> int:
        """Update status of all pending enhancements for a robot enhancement batch."""
        return await self.sql_uow.pending_enhancements.bulk_update_by_filter(
            filter_conditions={
                "robot_enhancement_batch_id": robot_enhancement_batch_id
            },
            status=status,
        )

    async def create_retry_pending_enhancements(
        self,
        expired_enhancements: list[PendingEnhancement],
        max_retry_count: int,
    ) -> list[PendingEnhancement]:
        """
        Create retry pending enhancements for expired ones.

        Args:
            expired_enhancements: List of expired pending enhancements
            max_retry_count: Maximum retry depth allowed

        Returns:
            List of newly created retry pending enhancements

        """
        enhancements_to_retry = []

        for expired_enhancement in expired_enhancements:
            retry_depth = await self.sql_uow.pending_enhancements.count_retry_depth(
                expired_enhancement.id
            )

            if retry_depth < max_retry_count:
                new_pending_enhancement = PendingEnhancement(
                    reference_id=expired_enhancement.reference_id,
                    robot_id=expired_enhancement.robot_id,
                    enhancement_request_id=expired_enhancement.enhancement_request_id,
                    source=expired_enhancement.source,
                    retry_of=expired_enhancement.id,
                    status=PendingEnhancementStatus.PENDING,
                )
                enhancements_to_retry.append(new_pending_enhancement)
            else:
                logger.warning(
                    "Pending enhancement exceeded retry limit",
                    pending_enhancement_id=expired_enhancement.id,
                    reference_id=expired_enhancement.reference_id,
                    retry_depth=retry_depth,
                    max_retry_count=max_retry_count,
                )

        if enhancements_to_retry:
            return await self.sql_uow.pending_enhancements.add_bulk(
                enhancements_to_retry
            )

        return []

    async def build_robot_enhancement_batch(
        self,
        robot_enhancement_batch: RobotEnhancementBatch,
        reference_data_file: BlobStorageFile,
    ) -> RobotEnhancementBatch:
        """
        Create a robot enhancement batch.

        Args:
            robot_enhancement_batch (RobotEnhancementBatch): The robot enhancement
                object.
            reference_data_file (BlobStorageFile): The blob storage file object.

        Returns:
            RobotEnhancementBatch: The created robot enhancement batch.

        """
        result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="robot_enhancement_batch_result_data",
            filename=f"{robot_enhancement_batch.id}_robot.jsonl",
        )

        return await self.sql_uow.robot_enhancement_batches.update_by_pk(
            pk=robot_enhancement_batch.id,
            reference_data_file=reference_data_file.to_sql(),
            result_file=result_file.to_sql(),
        )

    async def add_validation_result_file_to_enhancement_request(
        self,
        enhancement_request_id: UUID,
        validation_result_file: BlobStorageFile,
    ) -> EnhancementRequest:
        """Add a validation result file to a enhancement request."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id,
            validation_result_file=validation_result_file.to_sql(),
        )

    async def add_validation_result_file_to_robot_enhancement_batch(
        self,
        robot_enhancement_batch_id: UUID,
        validation_result_file: BlobStorageFile,
    ) -> RobotEnhancementBatch:
        """Add a validation result file to a robot enhancement batch."""
        return await self.sql_uow.robot_enhancement_batches.update_by_pk(
            pk=robot_enhancement_batch_id,
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

    async def _process_robot_error_line(
        self,
        robot_error: destiny_sdk.robots.LinkedRobotError,
        attempted_reference_ids: set[UUID],
    ) -> str:
        """Process a line containing a robot error."""
        trace_attribute(
            Attributes.REFERENCE_ID,
            str(robot_error.reference_id),
        )
        attempted_reference_ids.add(robot_error.reference_id)

        return self._anti_corruption_service.robot_result_validation_entry_to_sdk(
            RobotResultValidationEntry(
                reference_id=robot_error.reference_id,
                error=robot_error.message,
            )
        ).to_jsonl()

    async def _process_parse_failure_line(
        self,
        parse_failure: str,
        line_no: int,
    ) -> str:
        """Process a line that failed to parse."""
        logger.warning(
            "Failed to parse enhancement",
            line_no=line_no,
            error=parse_failure,
        )

        return self._anti_corruption_service.robot_result_validation_entry_to_sdk(
            RobotResultValidationEntry(
                error=parse_failure,
            )
        ).to_jsonl()

    async def _process_enhancement_line(  # noqa: PLR0913
        self,
        enhancement_to_add: destiny_sdk.enhancements.Enhancement,
        add_enhancement: Callable[
            [Enhancement], Awaitable[tuple[PendingEnhancementStatus, str]]
        ],
        line_no: int,
        attempted_reference_ids: set[UUID],
        results: ProcessedResults,
        successful_reference_ids: set[UUID],
        discarded_enhancement_reference_ids: set[UUID],
    ) -> str:
        """Process a line containing an enhancement to add."""
        trace_attribute(
            Attributes.REFERENCE_ID,
            str(enhancement_to_add.reference_id),
        )
        attempted_reference_ids.add(enhancement_to_add.reference_id)

        # NB this generates the UUID that we import into the database,
        # which is handy!
        enhancement = self._anti_corruption_service.enhancement_from_sdk(
            enhancement_to_add
        )
        trace_attribute(Attributes.ENHANCEMENT_ID, str(enhancement.id))

        status, message = await add_enhancement(enhancement)

        if status == PendingEnhancementStatus.COMPLETED:
            results.imported_enhancement_ids.add(enhancement.id)
            successful_reference_ids.add(enhancement_to_add.reference_id)

            return self._anti_corruption_service.robot_result_validation_entry_to_sdk(
                RobotResultValidationEntry(
                    reference_id=enhancement_to_add.reference_id,
                )
            ).to_jsonl()

        if status == PendingEnhancementStatus.DISCARDED:
            discarded_enhancement_reference_ids.add(enhancement_to_add.reference_id)

        logger.warning(
            "Failed to add enhancement",
            error=message,
            line_no=line_no,
            reference_id=enhancement.reference_id,
            enhancement_id=enhancement.id,
        )

        return self._anti_corruption_service.robot_result_validation_entry_to_sdk(
            RobotResultValidationEntry(
                reference_id=enhancement_to_add.reference_id,
                error=message,
            )
        ).to_jsonl()

    def _categorize_pending_enhancements(
        self,
        pending_enhancements: list[PendingEnhancement],
        successful_reference_ids: set[UUID],
        discarded_enhancement_reference_ids: set[UUID],
        results: ProcessedResults,
    ) -> None:
        """Categorize pending enhancements as successful or failed."""
        for pending_enhancement in pending_enhancements:
            if pending_enhancement.reference_id in successful_reference_ids:
                results.successful_pending_enhancement_ids.add(pending_enhancement.id)
            elif (
                pending_enhancement.reference_id in discarded_enhancement_reference_ids
            ):
                results.discarded_pending_enhancement_ids.add(pending_enhancement.id)
            else:
                results.failed_pending_enhancement_ids.add(pending_enhancement.id)

    async def process_robot_enhancement_batch_result(
        self,
        blob_repository: BlobRepository,
        result_file: BlobStorageFile,
        pending_enhancements: list[PendingEnhancement],
        add_enhancement: Callable[
            [Enhancement], Awaitable[tuple[PendingEnhancementStatus, str]]
        ],
        results: ProcessedResults,
    ) -> AsyncGenerator[str, None]:
        """
        Validate the result of a robot enhancement batch.

        This generator yields validation messages which are streamed into the
        result file of the robot enhancement batch.
        """
        expected_reference_ids = {pe.reference_id for pe in pending_enhancements}
        successful_reference_ids: set[UUID] = set()
        attempted_reference_ids: set[UUID] = set()
        discarded_enhancement_reference_ids: set[UUID] = set()
        # Track processed IDs for duplicate validation
        processed_reference_ids: set[UUID] = set()

        # Track if we've logged the biblio deprecation warning for this batch
        biblio_deprecation_logged = False

        async with blob_repository.stream_file_from_blob_storage(
            result_file,
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

                    # Log deprecation warning if client uses 'biblio' instead of
                    # 'pagination'. robot_id is bound to structlog context by the
                    # calling task.
                    if not biblio_deprecation_logged and '"biblio":' in line:
                        logger.warning(
                            "Client sent 'biblio' field instead of 'pagination'. "
                            "Please update to use 'pagination' field.",
                        )
                        biblio_deprecation_logged = True

                    validated_result = EnhancementResultValidator.from_raw(
                        line, line_no, expected_reference_ids, processed_reference_ids
                    )
                    line_no += 1

                    # Process the validated result line
                    result_entry = ""
                    if validated_result.robot_error:
                        # Track processed IDs here for clarity
                        ref_id = validated_result.robot_error.reference_id
                        if ref_id in expected_reference_ids:
                            processed_reference_ids.add(ref_id)
                        result_entry = await self._process_robot_error_line(
                            validated_result.robot_error,
                            attempted_reference_ids,
                        )
                    elif validated_result.parse_failure:
                        result_entry = await self._process_parse_failure_line(
                            validated_result.parse_failure,
                            line_no,
                        )
                    elif validated_result.enhancement_to_add:
                        # Track processed IDs here for clarity
                        processed_reference_ids.add(
                            validated_result.enhancement_to_add.reference_id
                        )
                        result_entry = await self._process_enhancement_line(
                            validated_result.enhancement_to_add,
                            add_enhancement,
                            line_no,
                            attempted_reference_ids,
                            results,
                            successful_reference_ids,
                            discarded_enhancement_reference_ids,
                        )

                    if result_entry:  # Only yield non-empty results
                        yield result_entry

        # Generate entries for missing references
        if missing_reference_ids := (expected_reference_ids - attempted_reference_ids):
            for missing_reference_id in missing_reference_ids:
                yield (
                    self._anti_corruption_service.robot_result_validation_entry_to_sdk(
                        RobotResultValidationEntry(
                            reference_id=missing_reference_id,
                            error="Requested reference not in enhancement result.",
                        )
                    ).to_jsonl()
                )

        # Categorize pending enhancements
        self._categorize_pending_enhancements(
            pending_enhancements,
            successful_reference_ids,
            discarded_enhancement_reference_ids,
            results,
        )
