"""The service for managing and interacting with robots."""

import destiny_sdk
import httpx
from fastapi import status
from pydantic import UUID4, HttpUrl

from app.core.auth import HMACSigningAuth
from app.core.config import get_settings
from app.core.exceptions import (
    RobotEnhancementError,
    RobotUnreachableError,
)
from app.domain.references.models.models import (
    EnhancementRequest,
    Reference,
)
from app.domain.robots.models import RobotConfig
from app.domain.robots.service import RobotService

MIN_FOR_5XX_STATUS_CODES = 500

settings = get_settings()


class RobotCommunicationService:
    """The service which manages interacting with robots."""

    def __init__(self, robots: RobotService) -> None:
        """Initialize the service with a unit of work."""
        self.robots = robots

    def get_robot_url(self, robot_id: UUID4) -> HttpUrl:
        """Get the url for a given robot id."""
        return self.robots.get_robot_url(robot_id)

    def get_robot_config(self, robot_id: UUID4) -> RobotConfig:
        """Get the config for a given robot id."""
        return self.robots.get_robot_config(robot_id)

    async def send_enhancement_request_to_robot(
        self,
        robot_config: RobotConfig,
        robot_request: destiny_sdk.robots.BatchRobotRequest,
    ) -> httpx.Response:
        """Send a request to a robot, handling error cases."""
        try:
            auth = HMACSigningAuth(robot_config.communication_secret_name)
            async with httpx.AsyncClient(auth=auth) as client:
                response = await client.post(
                    str(robot_config.robot_url).rstrip("/") + "/batch/",
                    json=robot_request.model_dump(mode="json"),
                )
        except httpx.RequestError as exception:
            error = f"Cannot request enhancement from Robot {robot_config.robot_id}."
            raise RobotUnreachableError(error) from exception

        if response.status_code != status.HTTP_202_ACCEPTED:
            if response.status_code >= MIN_FOR_5XX_STATUS_CODES:
                error = (
                    f"Cannot request enhancement from Robot {robot_config.robot_id}."
                )
                raise RobotUnreachableError(error)
            # Expect this is a 4xx
            raise RobotEnhancementError(detail=response.text)

        return response

    async def request_enhancement_from_robot(
        self,
        robot_config: RobotConfig,
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
            auth = HMACSigningAuth(robot_config.communication_secret_name)
            async with httpx.AsyncClient(auth=auth) as client:
                response = await client.post(
                    str(robot_config.robot_url).rstrip("/") + "/single/",
                    json=robot_request.model_dump(mode="json"),
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
