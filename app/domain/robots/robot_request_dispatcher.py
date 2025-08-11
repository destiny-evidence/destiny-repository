"""The service for managing and interacting with robots."""

import destiny_sdk
import httpx
from fastapi import status
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.core.config import get_settings
from app.core.exceptions import (
    RobotEnhancementError,
    RobotUnreachableError,
)
from app.core.telemetry.logger import get_logger
from app.domain.robots.models.models import Robot

MIN_FOR_5XX_STATUS_CODES = 500

settings = get_settings()
logger = get_logger(__name__)


class RobotRequestDispatcher:
    """Dispatcher for sending enhancement requests to robots."""

    def __init__(self) -> None:
        """Initialize the RobotRequestDispatcher."""
        self._httpx_instrumentor = HTTPXClientInstrumentor()

    async def send_enhancement_request_to_robot(
        self,
        endpoint: str,
        robot: Robot,
        robot_request: destiny_sdk.robots.RobotRequest
        | destiny_sdk.robots.BatchRobotRequest,
    ) -> httpx.Response:
        """Send a request to a robot, handling error cases."""
        try:
            client_secret = robot.get_client_secret()
            auth = destiny_sdk.client.HMACSigningAuth(
                secret_key=client_secret, client_id=robot.id
            )
            async with httpx.AsyncClient(auth=auth) as client:
                self._httpx_instrumentor.instrument_client(client)
                response = await client.post(
                    str(robot.base_url).rstrip("/") + endpoint,
                    json=robot_request.model_dump(mode="json"),
                )
        except httpx.RequestError as exception:
            logger.exception("Cannot reach robot", robot_id=robot.id)
            error = f"Cannot request enhancement from Robot {robot.id}."
            raise RobotUnreachableError(error) from exception

        if response.status_code != status.HTTP_202_ACCEPTED:
            if response.status_code >= MIN_FOR_5XX_STATUS_CODES:
                error = f"Cannot request enhancement from Robot {robot.id}."
                raise RobotUnreachableError(error)
            # Expect this is a 4xx
            raise RobotEnhancementError(detail=response.text)

        return response
