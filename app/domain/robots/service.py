"""Service for managing Robots."""

from pydantic import UUID4, HttpUrl

from app.domain.robots.models import Robot
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork


class RobotService(GenericService):
    """Service for creating and managing robots."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork) -> None:
        """Initialize the robots."""
        self.sql_uow = sql_uow

    async def _get_robot(self, robot_id: UUID4) -> Robot:
        """Return a given robot."""
        return await self.sql_uow.robots.get_by_pk(robot_id)

    async def get_robot_url(self, robot_id: UUID4) -> HttpUrl:
        """Return the url for a given robot."""
        robot = await self._get_robot(robot_id)
        return robot.base_url

    async def get_robot(self, robot_id: UUID4) -> Robot:
        """Return a given robot."""
        return await self._get_robot(robot_id)

    async def get_robot_secret(self, robot_id: UUID4) -> str:
        """Return secret used for signing requests sent to this robot."""
        # Secret to be stored in the azure keyvault
        # Currently just using secret name while testing
        robot = await self._get_robot(robot_id)
        return robot.client_secret.get_secret_value()
