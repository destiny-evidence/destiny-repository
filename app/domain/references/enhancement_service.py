"""The service for managing our enhancments and enhancement requests."""

from pydantic import UUID4

from app.core.exceptions import (
    RobotEnhancementError,
    RobotUnreachableError,
    WrongReferenceError,
)
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
)
from app.domain.robots.service import RobotService
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


class EnhancementService(GenericService):
    """The service which manages our enhancements and enhancement requests."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)

    async def _add_enhancement(
        self,
        enhancement: Enhancement,
    ) -> Enhancement:
        """Add an enhancement to a reference."""
        # Errors if reference doesn't exist
        await self.sql_uow.references.get_by_pk(enhancement.reference_id)
        return await self.sql_uow.enhancements.add(enhancement)

    async def _get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest:
        """Get an enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(enhancement_request_id)

    @unit_of_work
    async def request_reference_enhancement(
        self, enhancement_request: EnhancementRequest, robot_service: RobotService
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        reference = await self.sql_uow.references.get_by_pk(
            enhancement_request.reference_id, preload=["identifiers", "enhancements"]
        )

        robot_config = robot_service.get_robot_config(enhancement_request.robot_id)

        enhancement_request = await self.sql_uow.enhancement_requests.add(
            enhancement_request
        )

        try:
            await robot_service.request_enhancement_from_robot(
                robot_config=robot_config,
                enhancement_request=enhancement_request,
                reference=reference,
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
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest:
        """Get an enhancement request by request id."""
        return await self._get_enhancement_request(enhancement_request_id)

    @unit_of_work
    async def create_reference_enhancement(
        self,
        enhancement_request_id: UUID4,
        enhancement: Enhancement,
    ) -> EnhancementRequest:
        """Finalise the creation of an enhancement against a reference."""
        enhancement_request = await self._get_enhancement_request(
            enhancement_request_id
        )

        if enhancement_request.reference_id != enhancement.reference_id:
            detail = "enhancement is for a different reference than requested."
            raise WrongReferenceError(detail)

        await self._add_enhancement(enhancement)

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
