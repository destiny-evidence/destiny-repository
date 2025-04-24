"""The service for interacting with and managing robot requests."""

from pydantic import UUID4

from app.domain.references.models.models import (
    Enhancement,
    EnhancementCreate,
    EnhancementRequest,
    EnhancementRequestStatus,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


class EnhancementService(GenericService):
    """The service which manages our requests to robots for reference enhancement."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    @unit_of_work
    async def add_enhancement(
        self,
        reference_id: UUID4,
        enhancement: EnhancementCreate,
    ) -> Enhancement:
        """Add an enhancement to a reference."""
        reference = await self.sql_uow.references.get_by_pk(reference_id)
        if not reference:
            msg = f"reference {reference_id} does not exist"
            raise RuntimeError(msg)
        db_enhancement = Enhancement(
            reference_id=reference.id,
            **enhancement.model_dump(),
        )
        return await self.sql_uow.enhancements.add(db_enhancement)

    @unit_of_work
    async def request_reference_enhancement(
        self,
        enhancement_request: EnhancementRequest,
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        enhancement_request = await self.sql_uow.enhancement_requests.add(
            enhancement_request
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
    ) -> Enhancement:
        """Finalise the creation of an enhancement against a reference."""
        enhancement_request = await self.get_enhancement_request(enhancement_request_id)

        if not enhancement_request:
            msg = "Enhancement request does not exist. This should not happen"
            raise RuntimeError(msg)

        created_enhancement = await self.add_enhancement(
            reference_id=enhancement_request.reference_id, enhancement=enhancement
        )

        await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id,
            request_status=EnhancementRequestStatus.COMPLETED,
        )

        return created_enhancement

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
