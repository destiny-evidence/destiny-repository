"""The service for interacting with and managing robot requests."""

import httpx
import destiny_sdk
from fastapi import status
from pydantic import UUID4

from app.core.exceptions import NotFoundError
from app.domain.references.models.models import (
    Enhancement,
    EnhancementIn,
    EnhancementRequest,
    EnhancementRequestIn,
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

    @unit_of_work
    async def add_enhancement(
        self,
        reference_id: UUID4,
        enhancement: EnhancementIn,
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
        self, enhancement_request_in: EnhancementRequestIn
    ) -> EnhancementRequest:
        """Create an enhancement request and send it to robot."""
        reference = await self.sql_uow.references.get_by_pk(
            enhancement_request_in.reference_id, preload=["identifiers", "enhancements"]
        )

        if not reference:
            raise NotFoundError(
                detail=f"Reference with id {enhancement_request_in.reference_id} not found"
            )

        robot_url = self.robots.get_robot_url(enhancement_request_in.robot_id)

        if not robot_url:
            raise NotFoundError(
                detail=f"Robot with id {enhancement_request_in.robot_id} not found.",
            )

        enhancement_request = await self.sql_uow.enhancement_requests.add(
            EnhancementRequest(**enhancement_request_in.model_dump())
        )

        robot_request = destiny_sdk.robots.RobotRequest(
            id=enhancement_request.id,
            reference=destiny_sdk.references.Reference(**reference.model_dump()),
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
    ) -> EnhancementRequest | None:
        """Get an enhancement request by request id."""
        return await self.sql_uow.enhancement_requests.get_by_pk(enhancement_request_id)

    @unit_of_work
    async def get_enhancement_request(
        self,
        enhancement_request_id: UUID4,
    ) -> EnhancementRequest | None:
        """Get an enhancement request by request id."""
        return await self._get_enhancement_request(enhancement_request_id)

    @unit_of_work
    async def create_reference_enhancement(
        self,
        enhancement_request_id: UUID4,
        enhancement: EnhancementIn,
    ) -> Enhancement:
        """Finalise the creation of an enhancement against a reference."""
        enhancement_request = await self._get_enhancement_request(
            enhancement_request_id
        )

        if not enhancement_request:
            raise NotFoundError(
                detail=f"Enhancement request with id {enhancement_request_id} not found"
            )

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
