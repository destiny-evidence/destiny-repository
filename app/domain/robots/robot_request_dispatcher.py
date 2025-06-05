"""The service for managing and interacting with robots."""

import destiny_sdk
import httpx
from fastapi import status
from pydantic import UUID4

from app.core.config import get_settings
from app.core.exceptions import (
    RobotEnhancementError,
    RobotUnreachableError,
)
from app.domain.robots.models import Robot
from app.domain.robots.service import RobotService

MIN_FOR_5XX_STATUS_CODES = 500

settings = get_settings()


class RobotRequestDispatcher:
    """Dispatcher for sending enhancement requests to robots."""

    def __init__(self, robots: RobotService) -> None:
        """Initialize the dispatcher with existing robots."""
        self.robots = robots

    def get_robot_config(self, robot_id: UUID4) -> Robot:
        """Get the config for a given robot id."""
        return self.robots.get_robot_config(robot_id)

    async def send_enhancement_request_to_robot(
        self,
        endpoint: str,
        robot: Robot,
        robot_request: destiny_sdk.robots.RobotRequest
        | destiny_sdk.robots.BatchRobotRequest,
    ) -> httpx.Response:
        """Send a request to a robot, handling error cases."""
        try:
            auth = destiny_sdk.client.HMACSigningAuth(
                secret_key=robot.client_secret.get_secret_value(), client_id=robot.id
            )
            async with httpx.AsyncClient(auth=auth) as client:
                response = await client.post(
                    str(robot.base_url).rstrip("/") + endpoint,
                    json=robot_request.model_dump(mode="json"),
                )
        except httpx.RequestError as exception:
            error = f"Cannot request enhancement from Robot {robot.id}."
            raise RobotUnreachableError(error) from exception

        if response.status_code != status.HTTP_202_ACCEPTED:
            if response.status_code >= MIN_FOR_5XX_STATUS_CODES:
                error = f"Cannot request enhancement from Robot {robot.id}."
                raise RobotUnreachableError(error)
            # Expect this is a 4xx
            raise RobotEnhancementError(detail=response.text)

        return response
