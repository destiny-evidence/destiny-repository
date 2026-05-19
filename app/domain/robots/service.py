"""Service for managing Robots."""

import secrets
from uuid import UUID

from pydantic import SecretStr

from app.api.auth import ClientAuthInfo
from app.domain.robots.models.models import Robot
from app.domain.robots.services.access_control_service import (
    RobotAccessControlService,
)
from app.domain.robots.services.anti_corruption_service import (
    RobotAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.persistence.sql.uow import unit_of_work as sql_unit_of_work

ENOUGH_BYTES_FOR_SAFETY = 32


class RobotService(GenericService[RobotAntiCorruptionService]):
    """Service for creating and managing robots."""

    def __init__(
        self,
        anti_corruption_service: RobotAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
    ) -> None:
        """Initialize the robots."""
        super().__init__(anti_corruption_service, sql_uow)

    async def get_robot(self, robot_id: UUID) -> Robot:
        """Return a given robot."""
        return await self.sql_uow.robots.get_by_pk(robot_id)

    @sql_unit_of_work
    async def get_all_robots(self) -> list[Robot]:
        """Return all robots."""
        return await self.sql_uow.robots.get_all()

    @sql_unit_of_work
    async def get_robot_standalone(self, robot_id: UUID) -> Robot:
        """Return a given robot."""
        return await self.get_robot(robot_id)

    @sql_unit_of_work
    async def get_robot_auth_info(self, robot_id: UUID) -> ClientAuthInfo:
        """Return the HMAC secret and entitlements for a given robot."""
        robot = await self.get_robot(robot_id)
        return ClientAuthInfo(
            secret=robot.get_client_secret(),
            entitlements=robot.entitlements,
        )

    @sql_unit_of_work
    async def add_robot(
        self,
        robot: Robot,
        access_control_service: RobotAccessControlService,
    ) -> Robot:
        """Register a new robot."""
        robot.entitlements = access_control_service.resolve_robot_entitlements(
            submitted=robot.entitlements,
            existing=frozenset(),
        )
        robot.client_secret = SecretStr(secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY))
        return await self.sql_uow.robots.add(robot)

    @sql_unit_of_work
    async def update_robot(
        self,
        robot: Robot,
        access_control_service: RobotAccessControlService,
    ) -> Robot:
        """Update an existing robot."""
        existing = await self.sql_uow.robots.get_by_pk(robot.id)
        robot.entitlements = access_control_service.resolve_robot_entitlements(
            submitted=robot.entitlements,
            existing=existing.entitlements,
        )
        return await self.sql_uow.robots.merge(robot)

    @sql_unit_of_work
    async def cycle_robot_secret(self, robot_id: UUID) -> Robot:
        """Cycle the client secret for a given robot."""
        new_client_secret = secrets.token_hex(ENOUGH_BYTES_FOR_SAFETY)
        return await self.sql_uow.robots.update_by_pk(
            robot_id, client_secret=new_client_secret
        )
