"""The service for interacting with and managing references."""

from collections.abc import Awaitable, Callable
from typing import cast

import destiny_sdk
from pydantic import UUID4

from app.core.config import get_settings
from app.core.exceptions import (
    InvalidParentEnhancementError,
    RobotEnhancementError,
    RobotUnreachableError,
    SQLNotFoundError,
    WrongReferenceError,
)
from app.core.logger import get_logger
from app.domain.base import SDKJsonlMixin
from app.domain.imports.models.models import CollisionStrategy
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
    ExternalIdentifier,
    ExternalIdentifierSearch,
    ExternalIdentifierType,
    LinkedExternalIdentifier,
    Reference,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.batch_enhancement_service import (
    BatchEnhancementService,
)
from app.domain.references.services.ingestion_service import (
    IngestionService,
)
from app.domain.robots.robot_request_dispatcher import RobotRequestDispatcher
from app.domain.robots.service import RobotService
from app.domain.service import GenericService
from app.persistence.blob.repository import BlobRepository
from app.persistence.blob.stream import FileStream
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work
from app.utils.lists import list_chunker

logger = get_logger()
settings = get_settings()


class ReferenceService(GenericService):
    """The service which manages our references."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)
        self._ingestion_service = IngestionService(sql_uow)
        self._batch_enhancement_service = BatchEnhancementService(sql_uow)

    @unit_of_work
    async def get_reference(self, reference_id: UUID4) -> Reference:
        """Get a single reference by id."""
        return await self.sql_uow.references.get_by_pk(
            reference_id, preload=["identifiers", "enhancements"]
        )

    async def _add_enhancement(
        self, reference_id: UUID4, enhancement: Enhancement
    ) -> Reference:
        """Add an enhancement to a reference."""
        # This method is used internally and does not use the unit of work.
        if enhancement.reference_id != reference_id:
            detail = "Enhancement is for a different reference than requested."
            raise WrongReferenceError(detail)

        if enhancement.derived_from:
            try:
                await self.sql_uow.enhancements.verify_pk_existence(
                    enhancement.derived_from
                )
            except SQLNotFoundError as e:
                detail = f"Enhancements with ids {e.lookup_value} do not exist."
                raise InvalidParentEnhancementError(detail) from e

        reference = await self.sql_uow.references.get_by_pk(
            reference_id, preload=["enhancements", "identifiers"]
        )
        # This uses SQLAlchemy to treat References as an aggregate of enhancements.
        # All considered this is a naive implementation, but it works for now.
        reference.enhancements = [*(reference.enhancements or []), *[enhancement]]
        return await self.sql_uow.references.merge(reference)

    @unit_of_work
    async def add_enhancement(
        self, reference_id: UUID4, enhancement: Enhancement
    ) -> Reference:
        """Add an enhancement to a reference."""
        return await self._add_enhancement(reference_id, enhancement)

    async def _get_hydrated_references(
        self,
        reference_ids: list[UUID4],
        enhancement_types: list[EnhancementType] | None = None,
        external_identifier_types: list[ExternalIdentifierType] | None = None,
    ) -> list[Reference]:
        """Get a list of references with enhancements and identifiers by id."""
        return await self.sql_uow.references.get_hydrated(
            reference_ids,
            enhancement_types=[
                enhancement_type.value for enhancement_type in enhancement_types
            ]
            if enhancement_types
            else None,
            external_identifier_types=[
                external_identifier_type.value
                for external_identifier_type in external_identifier_types
            ]
            if external_identifier_types
            else None,
        )

    @unit_of_work
    async def get_reference_from_identifier(
        self, identifier: ExternalIdentifierSearch
    ) -> Reference:
        """Get a single reference by identifier."""
        db_identifier = (
            await self.sql_uow.external_identifiers.get_by_type_and_identifier(
                identifier.identifier_type,
                identifier.identifier,
                identifier.other_identifier_name,
            )
        )
        return await self.sql_uow.references.get_by_pk(
            db_identifier.reference_id, preload=["identifiers", "enhancements"]
        )

    @unit_of_work
    async def register_reference(self) -> Reference:
        """Create a new reference."""
        return await self.sql_uow.references.add(Reference())

    @unit_of_work
    async def add_identifier(
        self, reference_id: UUID4, identifier: ExternalIdentifier
    ) -> LinkedExternalIdentifier:
        """Register an import, persisting it to the database."""
        reference = await self.sql_uow.references.get_by_pk(reference_id)
        db_identifier = LinkedExternalIdentifier(
            reference_id=reference.id,
            identifier=identifier,
        )
        return await self.sql_uow.external_identifiers.add(db_identifier)

    async def _get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest:
        """Get an enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(enhancement_request_id)

    async def ingest_reference(
        self, record_str: str, entry_ref: int, collision_strategy: CollisionStrategy
    ) -> ReferenceCreateResult | None:
        """Ingest a reference from a file."""
        return await self._ingestion_service.ingest_reference(
            record_str, entry_ref, collision_strategy
        )

    @unit_of_work
    async def request_reference_enhancement(
        self,
        enhancement_request: EnhancementRequest,
        robot_service: RobotService,
        robot_request_dispatcher: RobotRequestDispatcher,
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        reference = await self.sql_uow.references.get_by_pk(
            enhancement_request.reference_id, preload=["identifiers", "enhancements"]
        )

        robot = await robot_service.get_robot(enhancement_request.robot_id)

        enhancement_request = await self.sql_uow.enhancement_requests.add(
            enhancement_request
        )

        robot_request = destiny_sdk.robots.RobotRequest(
            id=enhancement_request.id,
            reference=await reference.to_sdk(),
            extra_fields=enhancement_request.enhancement_parameters,
        )

        try:
            await robot_request_dispatcher.send_enhancement_request_to_robot(
                endpoint="/single/", robot=robot, robot_request=robot_request
            )
        except RobotUnreachableError as exception:
            return await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.FAILED,
                error=exception.detail,
            )
        except RobotEnhancementError as exception:
            return await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.REJECTED,
                error=exception.detail,
            )

        return await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id,
            request_status=EnhancementRequestStatus.ACCEPTED,
        )

    @unit_of_work
    async def register_batch_reference_enhancement_request(
        self,
        enhancement_request: BatchEnhancementRequest,
    ) -> BatchEnhancementRequest:
        """Create a batch enhancement request."""
        await self.sql_uow.references.verify_pk_existence(
            enhancement_request.reference_ids
        )

        # Add any extra parameters here!

        return await self.sql_uow.batch_enhancement_requests.add(enhancement_request)

    @unit_of_work
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest:
        """Get an enhancement request by request id."""
        return await self._get_enhancement_request(enhancement_request_id)

    @unit_of_work
    async def get_batch_enhancement_request(
        self,
        batch_enhancement_request_id: UUID4,
    ) -> BatchEnhancementRequest:
        """Get a batch enhancement request by request id."""
        return await self.sql_uow.batch_enhancement_requests.get_by_pk(
            batch_enhancement_request_id
        )

    @unit_of_work
    async def create_reference_enhancement_from_request(
        self,
        enhancement_request_id: UUID4,
        enhancement: Enhancement,
    ) -> EnhancementRequest:
        """Finalise the creation of an enhancement against a reference."""
        enhancement_request = await self._get_enhancement_request(
            enhancement_request_id
        )

        await self._add_enhancement(enhancement_request.reference_id, enhancement)

        return await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id,
            request_status=EnhancementRequestStatus.COMPLETED,
        )

    @unit_of_work
    async def mark_enhancement_request_failed(
        self, enhancement_request_id: UUID4, error: str
    ) -> EnhancementRequest:
        """Mark an enhancement request as failed and supply error message."""
        return await self.sql_uow.enhancement_requests.update_by_pk(
            pk=enhancement_request_id,
            request_status=EnhancementRequestStatus.FAILED,
            error=error,
        )

    @unit_of_work
    async def collect_and_dispatch_references_for_batch_enhancement(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        robot_service: RobotService,
        robot_request_dispatcher: RobotRequestDispatcher,
        blob_repository: BlobRepository,
    ) -> None:
        """Collect and dispatch references for batch enhancement."""
        robot = await robot_service.get_robot(batch_enhancement_request.robot_id)
        file_stream = FileStream(
            # Handle Python's type invariance by casting the function type. We know
            # Reference is a subclass of SDKJsonlMixin.
            cast(
                Callable[..., Awaitable[list[SDKJsonlMixin]]],
                self._get_hydrated_references,
            ),
            [
                {
                    "reference_ids": reference_id_chunk,
                }
                for reference_id_chunk in list_chunker(
                    batch_enhancement_request.reference_ids,
                    settings.upload_file_chunk_size_override.get(
                        "batch_enhancement_request_reference_data",
                        settings.default_upload_file_chunk_size,
                    ),
                )
            ],
        )

        robot_request = await self._batch_enhancement_service.build_robot_request(
            blob_repository, file_stream, batch_enhancement_request
        )

        try:
            await robot_request_dispatcher.send_enhancement_request_to_robot(
                endpoint="/batch/",
                robot=robot,
                robot_request=robot_request,
            )
        except RobotUnreachableError as exception:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.FAILED,
                error=exception.detail,
            )
        except RobotEnhancementError as exception:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.REJECTED,
                error=exception.detail,
            )
        else:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.ACCEPTED,
            )

    @unit_of_work
    async def validate_and_import_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        blob_repository: BlobRepository,
    ) -> None:
        """
        Validate and import the result of a batch enhancement request.

        This process:
        - streams the result of the batch enhancement request line-by-line
        - adds the enhancement to the database
        - streams the validation result to the blob storage service line-by-line
        - does some final validation of missing references and updates the request
        """
        validation_result_file = await blob_repository.upload_file_to_blob_storage(
            content=FileStream(
                generator=self._batch_enhancement_service.process_batch_enhancement_result(
                    blob_repository=blob_repository,
                    batch_enhancement_request=batch_enhancement_request,
                    add_enhancement=self.handle_batch_enhancement_result_entry,
                )
            ),
            path="batch_enhancement_result",
            filename=f"{batch_enhancement_request.id}_repo.jsonl",
        )

        await self._batch_enhancement_service.add_validation_result_file_to_batch_enhancement_request(  # noqa: E501
            batch_enhancement_request.id, validation_result_file
        )

    async def handle_batch_enhancement_result_entry(
        self,
        enhancement: Enhancement,
    ) -> tuple[bool, str]:
        """Handle the import of a single batch enhancement result entry."""
        try:
            await self._add_enhancement(
                enhancement.reference_id,
                enhancement,
            )
        except SQLNotFoundError:
            return (
                False,
                "Reference does not exist.",
            )
        except Exception:
            logger.exception(
                "Failed to add enhancement to reference.",
                extra={
                    "reference_id": enhancement.reference_id,
                    "enhancement": enhancement,
                },
            )
            return (
                False,
                "Failed to add enhancement to reference.",
            )

        return (
            True,
            "Enhancement added.",
        )

    @unit_of_work
    async def mark_batch_enhancement_request_failed(
        self,
        batch_enhancement_request_id: UUID4,
        error: str,
    ) -> BatchEnhancementRequest:
        """Mark a batch enhancement request as failed and supply error message."""
        return (
            await self._batch_enhancement_service.mark_batch_enhancement_request_failed(
                batch_enhancement_request_id, error
            )
        )

    @unit_of_work
    async def update_batch_enhancement_request_status(
        self,
        batch_enhancement_request_id: UUID4,
        status: BatchEnhancementRequestStatus,
    ) -> BatchEnhancementRequest:
        """Update a batch enhancement request."""
        return await self._batch_enhancement_service.update_batch_enhancement_request_status(  # noqa: E501
            batch_enhancement_request_id, status
        )
