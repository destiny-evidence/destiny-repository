"""Service for managing Robots."""

import secrets

from pydantic import UUID4, SecretStr

from app.domain.robots.models.models import Robot
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work as sql_unit_of_work
from app.persistence.es.uow import AsyncESUnitOfWork, unit_of_work as es_unit_of_work

ENOUGH_BYTES_FOR_SAFETY = 32


class RobotService(GenericService):
    """Service for creating and managing robots."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, es_uow: AsyncESUnitOfWork) -> None:
        """Initialize the robots."""
        self.sql_uow = sql_uow
        self.es_uow = es_uow

    async def get_robot(self, robot_id: UUID4) -> Robot:
        """Return a given robot."""
        return await self.sql_uow.robots.get_by_pk(robot_id)

    @sql_unit_of_work
    async def get_robot_standalone(self, robot_id: UUID4) -> Robot:
        """Return a given robot."""
        return await self.get_robot(robot_id)

    async def get_robot_secret(self, robot_id: UUID4) -> str:
        """Return secret used for signing requests sent to this robot."""
        # Secret to be stored in the azure keyvault
        # Currently just using secret name while testing
        robot = await self.get_robot(robot_id)
        return await robot.get_client_secret()

    @sql_unit_of_work
    async def get_robot_secret_standalone(self, robot_id: UUID4) -> str:
        """Return secret used for signing requests sent to this robot."""
        return await self.get_robot_secret(robot_id=robot_id)

    @sql_unit_of_work
    async def add_robot(self, robot: Robot) -> Robot:
        """Register a new robot."""
        robot.client_secret = SecretStr(secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY))
        return await self.sql_uow.robots.add(robot)

    @sql_unit_of_work
    async def update_robot(self, robot: Robot) -> Robot:
        """Update an existing robot."""
        return await self.sql_uow.robots.merge(robot)

    @sql_unit_of_work
    async def cycle_robot_secret(self, robot_id: UUID4) -> Robot:
        """Cycle the client secret for a given robot."""
        new_client_secret = secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY)
        return await self.sql_uow.robots.update_by_pk(
            robot_id, client_secret=new_client_secret
        )
