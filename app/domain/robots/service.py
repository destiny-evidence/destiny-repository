"""The service for managing and interacting with robots."""

import destiny_sdk
import httpx
from fastapi import status
from pydantic import UUID4, HttpUrl

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.models.models import EnhancementRequest, Reference
from app.domain.robots.models import Robots
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork

MIN_FOR_5XX_STATUS_CODES = 500


class RobotService(GenericService):
    """The service which manages interacting with robots."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, robots: Robots) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)
        self.robots = robots

    def get_robot_url(self, robot_id: UUID4) -> HttpUrl:
        """Get the url for a given robot id."""
        return self.robots.get_robot_url(robot_id)

    async def request_enhancement_from_robot(
        self,
        robot_url: HttpUrl,
        enhancement_request: EnhancementRequest,
        reference: Reference,
    ) -> httpx.Response:
        """Request an enhancement from a robot."""
        robot_request = destiny_sdk.robots.RobotRequest(
            id=enhancement_request.id,
            reference=destiny_sdk.references.Reference(**reference.model_dump()),
            extra_fields=enhancement_request.enhancement_parameters,
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    str(robot_url), json=robot_request.model_dump(mode="json")
                )
        except httpx.RequestError as exception:
            error = (
                f"Cannot request enhancement from Robot {enhancement_request.robot_id}."
            )
            raise RobotUnreachableError(error) from exception

        if response.status_code != status.HTTP_202_ACCEPTED:
            if response.status_code >= MIN_FOR_5XX_STATUS_CODES:
                error = f"Cannot request enhancement from Robot {enhancement_request.robot_id}."  # noqa: E501
                raise RobotUnreachableError(error)
            # Expect this is a 4xx
            raise RobotEnhancementError(detail=response.text)

        return response
