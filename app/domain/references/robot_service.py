"""The service for interacting with and managing robot requests."""

from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementRequest,
    EnhancementRequestStatus,
    EnhancementType,
)
from app.domain.references.service import ReferenceService
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


class RobotService(GenericService):
    """The service which manages our requests to robots for reference enhancement."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    @unit_of_work
    async def request_reference_enhancement(
        self,
        reference_id: UUID4,
        enhancement_type: EnhancementType,
        reference_service: ReferenceService,
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        reference = await reference_service.get_reference(reference_id)

        if not reference:
            msg = "Reference does not exist. This should not happen."
            raise RuntimeError(msg)

        enhancement_request = await self.sql_uow.enhancement_requests.add(
            EnhancementRequest(
                reference_id=reference_id,
                enhancement_type=enhancement_type,
            )
        )

        # Send stuff off to the robot
        # Either return accepted or rejected based on initial robot response

        return await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id, request_status=EnhancementRequestStatus.ACCEPTED
        )

    @unit_of_work
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest | None:
        """Get an enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(enhancement_request_id)

    @unit_of_work
    async def create_reference_enhancement(
        self,
        enhancement_request_id: UUID4,
        enhancement: EnhancementCreate,
        reference_service: ReferenceService,
    ) -> Enhancement:
        """Finalise the creation of an enhancement against a reference."""
        enhancement_request = await self.get_enhancement_request(enhancement_request_id)

        if not enhancement_request:
            msg = "Enhancement request does not exist. This should not happen"
            raise RuntimeError(msg)

        if enhancement.enhancement_type != enhancement_request.enhancement_type:
            msg = "Enhancement creation is for different enhancement type to request"
            raise RuntimeError(msg)

        created_enhancement = await reference_service.add_enhancement(
            reference_id=enhancement_request.reference_id, enhancement=enhancement
        )

        if created_enhancement:
            await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.COMPLETED,
            )
        else:
            await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.FAILED,
                # want to pass error here
            )

        return created_enhancement
