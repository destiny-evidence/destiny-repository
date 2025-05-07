"""The service for interacting with and managing robot requests."""

import httpx
from destiny_sdk.core import Reference as RobotReference
from destiny_sdk.robots import RobotRequest
from fastapi import status
from pydantic import UUID4

from app.core.exceptions import NotFoundError, WrongReferenceError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementRequest,
    EnhancementRequestStatus,
)
from app.domain.robots import Robots
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work


class EnhancementService(GenericService):
    """The service which manages our requests to robots for reference enhancement."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, robots: Robots) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)
        self.robots = robots

    async def _add_enhancement(
        self,
        enhancement: Enhancement,
    ) -> Enhancement:
        """Add an enhancement to a reference."""
        reference = await self.sql_uow.references.get_by_pk(enhancement.reference_id)

        if not reference:
            raise NotFoundError(
                detail=f"Reference {enhancement.reference_id} not found"
            )

        return await self.sql_uow.enhancements.add(enhancement)

    @unit_of_work
    async def request_reference_enhancement(
        self, enhancement_request: EnhancementRequest
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        reference = await self.sql_uow.references.get_by_pk(
            enhancement_request.reference_id, preload=["identifiers", "enhancements"]
        )

        if not reference:
            raise NotFoundError(
                detail=f"Reference {enhancement_request.reference_id} not found"
            )

        robot_url = self.robots.get_robot_url(enhancement_request.robot_id)

        if not robot_url:
            raise NotFoundError(
                detail=f"Robot {enhancement_request.robot_id} not found.",
            )

        enhancement_request = await self.sql_uow.enhancement_requests.add(
            enhancement_request
        )

        robot_request = RobotRequest(
            id=enhancement_request.id,
            reference=RobotReference(**reference.model_dump()),
            extra_fields=enhancement_request.enhancement_parameters,
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                str(robot_url), json=robot_request.model_dump(mode="json")
            )

        if response.status_code != status.HTTP_202_ACCEPTED:
            return await self.sql_uow.enhancement_requests.update_by_pk(
                enhancement_request.id,
                request_status=EnhancementRequestStatus.REJECTED,
                error=response.json()["message"],
            )

        return await self.sql_uow.enhancement_requests.update_by_pk(
            enhancement_request.id, request_status=EnhancementRequestStatus.ACCEPTED
        )

    async def _get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest:
        """Get an enhancement request by request id."""
        enhancement_request = await self.sql_uow.enhancement_requests.get_by_pk(
            enhancement_request_id
        )

        if not enhancement_request:
            detail = f"Enhancement request {enhancement_request_id} not found."
            raise NotFoundError(
                detail=detail,
            )

        return enhancement_request

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
        try:
            return await self.sql_uow.enhancement_requests.update_by_pk(
                pk=enhancement_request_id,
                request_status=EnhancementRequestStatus.FAILED,
                error=error,
            )
        except NotFoundError as exception:
            raise NotFoundError(
                detail=f"Enhancement request {enhancement_request_id} not found."
            ) from exception
