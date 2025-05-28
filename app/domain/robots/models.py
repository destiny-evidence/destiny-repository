"""
Class for managing robots used to request enhancements from.

Intended to be replaced with a Model and a persistence class at a later date.
"""

from uuid import UUID

from pydantic import BaseModel, HttpUrl

from app.core.exceptions import NotFoundError
from app.domain.references.models.models import EnhancementType, ExternalIdentifierType


class RobotConfig(BaseModel):
    """
    Primitive configuration for a robot.

    To be replaced with a full persistence implementation at a later date.
    """

    robot_id: UUID
    robot_url: HttpUrl
    # Future implementation should configure whether each dependency is required
    # or provided on a best-efforts basis.
    dependent_enhancements: list[EnhancementType]
    dependent_identifiers: list[ExternalIdentifierType]
    # Secret to be stored in the azure keyvault
    communication_secret_name: str


class Robots:
    """Class for keeping track of robots."""

    known_robots: dict[UUID, RobotConfig]

    def __init__(self, known_robots: list[RobotConfig]) -> None:
        """Initialize the robots."""
        self.known_robots = {robot.robot_id: robot for robot in known_robots}

    def __call__(self):  # noqa: ANN204
        """Allow us to use this class as a dependency."""
        return self

    def get_robot_url(self, robot_id: UUID) -> HttpUrl:
        """Return the url for a given robot."""
        return self.get_robot_config(robot_id).robot_url

    def get_robot_config(self, robot_id: UUID) -> RobotConfig:
        """Return the config for a given robot."""
        robot = self.known_robots.get(robot_id, None)

        if not robot:
            error = f"Robot {robot_id} does not exist."
            raise NotFoundError(detail=error)

        return robot
