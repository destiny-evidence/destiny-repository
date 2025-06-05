"""Service for managing Robots."""

from uuid import UUID

from pydantic import HttpUrl

from app.core.exceptions import NotFoundError
from app.domain.robots.models import Robot


class RobotService:
    """Class for keeping track of robots."""

    known_robots: dict[UUID, Robot]

    def __init__(self, known_robots: list[Robot]) -> None:
        """Initialize the robots."""
        self.known_robots = {robot.id: robot for robot in known_robots}

    def __call__(self):  # noqa: ANN204
        """Allow us to use this class as a dependency."""
        return self

    def get_robot_url(self, robot_id: UUID) -> HttpUrl:
        """Return the url for a given robot."""
        return self.get_robot_config(robot_id).base_url

    def get_robot_config(self, robot_id: UUID) -> Robot:
        """Return the config for a given robot."""
        robot = self.known_robots.get(robot_id, None)

        if not robot:
            error = f"Robot {robot_id} does not exist."
            raise NotFoundError(detail=error)

        return robot

    async def get_robot_secret(self, robot_id: UUID) -> str:
        """Return secret used for signing requests sent to this robot."""
        # Secret to be stored in the azure keyvault
        # Currently just using secret name while testing
        return self.get_robot_config(robot_id).client_secret.get_secret_value()
