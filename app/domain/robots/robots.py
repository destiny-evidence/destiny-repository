"""
Class for managing robots used to request enhancements from.

Intended to be replaced with database storage at a later date.
"""

from uuid import UUID

from pydantic import HttpUrl


class Robots:
    """Class for keeping track of robots."""

    known_robots: dict[UUID, HttpUrl]

    def __init__(self, known_robots: dict[UUID, HttpUrl]) -> None:
        """Initialize the robots."""
        self.known_robots = known_robots

    def __call__(self):  # noqa: ANN204
        """Allow us to use this class as a dependency."""
        return self

    def get_robot_url(self, robot_id: UUID) -> HttpUrl | None:
        """Return the url for a given robot."""
        return self.known_robots.get(robot_id, None)
